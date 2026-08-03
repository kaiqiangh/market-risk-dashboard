"""Provider 抽象与降级链（架构 §1.4）。

- BaseProvider：统一接口（health + 各域方法），任何外部数据必须经此接口。
- ProviderRegistry：域 → 有序 Provider 列表 + last-good 缓存 + 降级标记。
- 降级链（必须实现为可测试用例）：
    主 Provider 失败/超时/限速 → 指数退避重试（≤2 次，jitter）
    → 备用 Provider → last-good 缓存 → 标记 degraded、降低 data_quality
    → 全部失败：freshness=missing，payload 保留上次数据 + stale 标记
- 任何 Provider 异常不得中断整条管道（Collector 捕获→degraded→继续）。
"""

from __future__ import annotations

import json
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel, Field

from pipeline.settings import Settings

# 默认超时/重试（可由 config/sources.yaml degrade 覆盖）
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 1.0


class ProviderError(Exception):
    """Provider 层错误（网络/限流/解析/业务失败）。管道不得因此崩溃。"""


class ProviderHealth(BaseModel):
    provider: str
    ok: bool
    latency_ms: float | None = None
    error: str | None = None
    checked_at: str | None = None


class QuoteResult(BaseModel):
    symbol: str
    price: float = Field(allow_inf_nan=False)
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    volume: float | None = None
    source: str = ""
    provider: str = ""
    updated_at: str | None = None
    is_proxy: bool = Field(default=False, description="备用源/缓存/代理时 True")


class HistoryResult(BaseModel):
    symbol: str
    provider: str
    rows: list[dict[str, Any]]
    period: str = "1y"


# 需要类型还原的方法（缓存重建用）
_RESULT_TYPES: dict[str, type] = {"get_quote": QuoteResult, "get_history": HistoryResult}


class BaseProvider(ABC):
    """所有外部数据提供方必须继承。方法失败抛 ProviderError。"""

    name: str = "base"
    priority: int = 100  # 数字越小越优先
    domain: str = "general"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    @abstractmethod
    def health(self) -> ProviderHealth:
        """健康检查（轻量，失败不抛异常）。"""

    # ---- 行情域 ----

    def get_quote(self, symbol: str) -> QuoteResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:  # pragma: no cover
        raise NotImplementedError

    # ---- 宏观域 ----

    def get_series(self, series_id: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover

    # ---- 加密域 ----

    def get_crypto_market(self) -> dict[str, Any]:
        raise NotImplementedError  # pragma: no cover

    # ---- 日历域 ----

    def get_earnings_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover

    # ---- 新闻域 ----

    def fetch_news(self) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    jitter: bool = True,
) -> T:
    """指数退避重试（≤ max_retries 次）。最后一次失败原样抛出。"""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = backoff_base * (2 ** (attempt - 1))
            if jitter:
                delay *= 0.5 + random.random()
            time.sleep(delay)


T = TypeVar("T")


class ProviderRegistry:
    """维护"域 → 有序 Provider 列表"与 last-good 缓存（架构 §1.4）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        sources = self.settings.load_sources()
        degrade = sources.get("degrade", {})
        self.max_retries = int(degrade.get("max_retries", DEFAULT_MAX_RETRIES))
        self.backoff_base = float(degrade.get("backoff_base_seconds", DEFAULT_BACKOFF_BASE))
        self.jitter = bool(degrade.get("jitter", True))
        self.degrade_factor = float(degrade.get("data_quality_degrade_factor", 0.8))
        cache_dir = self.settings.artifacts_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir: Path = cache_dir
        self._providers: dict[str, list[BaseProvider]] = {}
        self.health_map: dict[str, ProviderHealth] = {}
        self.degraded_domains: set[str] = set()

    # ---- 注册 ----

    def register(self, domain: str, provider: BaseProvider) -> None:
        providers = self._providers.setdefault(domain, [])
        providers.append(provider)
        providers.sort(key=lambda p: p.priority)

    def register_all(self, providers: list[BaseProvider]) -> None:
        for provider in providers:
            self.register(provider.domain, provider)

    def providers_for(self, domain: str) -> list[BaseProvider]:
        return list(self._providers.get(domain, []))

    # ---- last-good 缓存 ----

    def _cache_path(self, domain: str, key: str) -> Path:
        return self.cache_dir / f"{domain}__{key}.json"

    def _load_last_good(self, domain: str, key: str, method: str) -> dict[str, Any] | Any | None:
        path = self._cache_path(domain, key)
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        data = cached.get("data") if isinstance(cached, dict) else cached
        restore_type = _RESULT_TYPES.get(method)
        if restore_type is not None and isinstance(data, dict):
            try:
                return restore_type.model_validate(data)
            except Exception:  # noqa: BLE001
                return None
        return data

    def _save_last_good(self, domain: str, key: str, method: str, payload: Any) -> None:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(domain, key).write_text(
                json.dumps({"method": method, "data": data}, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except OSError:
            pass

    # ---- 统一降级调用 ----

    def call(
        self,
        domain: str,
        method: str,
        key: str,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按降级链调用 Provider 方法，返回 (result, meta)。

        meta 含 provider、used_fallback、from_cache、degraded。
        全部失败时：尝试 last-good 缓存 → 仍失败抛 ProviderError。
        """
        kwargs = kwargs or {}
        providers = self.providers_for(domain)
        errors: list[str] = []
        used_fallback = False

        for index, provider in enumerate(providers):
            try:
                result = retry_with_backoff(
                    lambda p=provider: getattr(p, method)(*args, **kwargs),
                    max_retries=self.max_retries,
                    backoff_base=self.backoff_base,
                    jitter=self.jitter,
                )
                meta = {
                    "provider": provider.name,
                    "used_fallback": index > 0,
                    "from_cache": False,
                    "degraded": index > 0,
                }
                if index > 0:
                    self.degraded_domains.add(domain)
                self._save_last_good(domain, key, method, result)
                return {"result": result, "meta": meta}
            except Exception as exc:  # noqa: BLE001 - 降级链必须吞掉 Provider 异常
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue

        # 全部 Provider 失败 → last-good 缓存
        cached = self._load_last_good(domain, key, method)
        if cached is not None:
            self.degraded_domains.add(domain)
            return {
                "result": cached,
                "meta": {
                    "provider": "last-good",
                    "used_fallback": True,
                    "from_cache": True,
                    "degraded": True,
                    "errors": errors,
                },
            }

        raise ProviderError(f"[{domain}] 所有 Provider 失败: {'; '.join(errors)}")

    # ---- 状态 ----

    def status(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for domain, providers in self._providers.items():
            out[domain] = []
            for provider in providers:
                health = provider.health()
                self.health_map[provider.name] = health
                out[domain].append(health.model_dump())
        return out
