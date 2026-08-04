"""Provider abstraction and degradation chain (architecture §1.4).

- BaseProvider: unified interface (health + per-domain methods); all external data must go through it.
- ProviderRegistry: domain → ordered Provider list + last-good cache + degraded markers.
- Degradation chain (must be implementable as test cases):
    primary Provider failure/timeout/rate limit → exponential backoff retry (≤2 times, jitter)
    → fallback Provider → last-good cache → mark degraded, lower data_quality
    → all failed: freshness=missing, payload keeps last data + stale marker
- No Provider exception may interrupt the whole pipeline (Collector catches → degraded → continue).
"""

from __future__ import annotations

import json
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel, Field

from pipeline.degrade import degrade_factor as resolve_degrade_factor
from pipeline.settings import Settings

# Default timeout/retry (overridable by config/sources.yaml degrade)
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 1.0


class ProviderError(Exception):
    """Provider-layer error (network/rate limit/parse/business failure). The pipeline must not crash on it."""


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
    is_proxy: bool = Field(default=False, description="True when fallback source/cache/proxy")


class HistoryResult(BaseModel):
    symbol: str
    provider: str
    rows: list[dict[str, Any]]
    period: str = "1y"


# Methods that need type restoration (for cache rebuild)
_RESULT_TYPES: dict[str, type] = {"get_quote": QuoteResult, "get_history": HistoryResult}


class BaseProvider(ABC):
    """All external data providers must inherit. Methods raise ProviderError on failure."""

    name: str = "base"
    priority: int = 100  # smaller number = higher priority
    domain: str = "general"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    @abstractmethod
    def health(self) -> ProviderHealth:
        """Health check (lightweight, does not raise on failure)."""

    # ---- Quotes domain ----

    def get_quote(self, symbol: str) -> QuoteResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:  # pragma: no cover
        raise NotImplementedError

    # ---- Macro domain ----

    def get_series(self, series_id: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover

    # ---- Crypto domain ----

    def get_crypto_market(self) -> dict[str, Any]:
        raise NotImplementedError  # pragma: no cover

    # ---- Calendar domain ----

    def get_earnings_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover

    # ---- News domain ----

    def fetch_news(self) -> list[dict[str, Any]]:
        raise NotImplementedError  # pragma: no cover


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    jitter: bool = True,
) -> T:
    """Exponential backoff retry (≤ max_retries times). The last failure is re-raised as-is."""
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
    """Maintains the "domain → ordered Provider list" and the last-good cache (architecture §1.4)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        sources = self.settings.load_sources()
        degrade = sources.get("degrade", {})
        self.max_retries = int(degrade.get("max_retries", DEFAULT_MAX_RETRIES))
        self.backoff_base = float(degrade.get("backoff_base_seconds", DEFAULT_BACKOFF_BASE))
        self.jitter = bool(degrade.get("jitter", True))
        # Single source of truth (#62): pass the already-parsed mapping so this does not
        # re-read sources.yaml.
        self.degrade_factor = resolve_degrade_factor(sources=sources)
        cache_dir = self.settings.artifacts_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir: Path = cache_dir
        self._providers: dict[str, list[BaseProvider]] = {}
        self.health_map: dict[str, ProviderHealth] = {}
        self.degraded_domains: set[str] = set()

    # ---- Registration ----

    def register(self, domain: str, provider: BaseProvider) -> None:
        providers = self._providers.setdefault(domain, [])
        providers.append(provider)
        providers.sort(key=lambda p: p.priority)

    def register_all(self, providers: list[BaseProvider]) -> None:
        for provider in providers:
            self.register(provider.domain, provider)

    def providers_for(self, domain: str) -> list[BaseProvider]:
        return list(self._providers.get(domain, []))

    # ---- last-good cache ----

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

    # ---- Unified degraded call ----

    def call(
        self,
        domain: str,
        method: str,
        key: str,
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a Provider method along the degradation chain, returning (result, meta).

        meta contains provider, used_fallback, from_cache, degraded.
        When all fail: try the last-good cache → still fail raises ProviderError.
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
            except Exception as exc:  # noqa: BLE001 - the degradation chain must swallow Provider exceptions
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue

        # All Providers failed → last-good cache
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

        raise ProviderError(f"[{domain}] all Providers failed: {'; '.join(errors)}")

    # ---- Status ----

    def status(self) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for domain, providers in self._providers.items():
            out[domain] = []
            for provider in providers:
                health = provider.health()
                self.health_map[provider.name] = health
                out[domain].append(health.model_dump())
        return out
