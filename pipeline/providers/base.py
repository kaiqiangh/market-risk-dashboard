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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from pydantic import BaseModel, Field

from pipeline.degrade import degrade_factor as resolve_degrade_factor
from pipeline.settings import Settings
from pipeline.utils import now_utc

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
        # #102: the cache directory is config (`degrade.last_good_cache_dir`), resolved
        # against the project root when relative — it used to be hardcoded to
        # `artifacts/cache` here while the config key sat unused.
        raw_cache_dir = str(degrade.get("last_good_cache_dir", "artifacts/cache"))
        cache_path = Path(raw_cache_dir)
        self.cache_dir: Path = (
            cache_path if cache_path.is_absolute() else self.settings.project_root / cache_path
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._providers: dict[str, list[BaseProvider]] = {}
        self.health_map: dict[str, ProviderHealth] = {}
        self.degraded_domains: set[str] = set()
        #: Domain → meta of the most recent successful call (#65): the provider that answered.
        self._last_outcome: dict[str, dict[str, Any]] = {}

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

    def _load_last_good(self, domain: str, key: str, method: str) -> tuple[Any, dict[str, Any]] | None:
        """Load a valid last-good cache entry, or ``None`` when it cannot be served (#66).

        A cache entry is served only when it is dated and younger than
        ``degrade.cache_max_age_hours``. Ruling C: an undated entry (the pre-#66 disk
        format) is treated as beyond the maximum age. Returns ``(data, meta)`` where meta
        names the originating provider and the original ``fetched_at`` — the caller
        (``call()``) publishes that provider in the provenance descriptor instead of the
        ``last-good`` placeholder.
        """
        from pipeline.degrade import cache_max_age_hours

        path = self._cache_path(domain, key)
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(cached, dict):
            return None
        fetched_at = cached.get("fetched_at")
        if not isinstance(fetched_at, str):
            # Ruling C: legacy undated entry — expired by definition.
            return None
        try:
            fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
        age_hours = max(0.0, (datetime.now(UTC) - fetched).total_seconds() / 3600.0)
        if age_hours > cache_max_age_hours():
            return None

        data = cached.get("data")
        provider = str(cached.get("provider", "unknown"))
        restore_type = _RESULT_TYPES.get(method)
        if restore_type is not None and isinstance(data, dict):
            try:
                data = restore_type.model_validate(data)
            except Exception:  # noqa: BLE001
                return None
        return data, {"provider": provider, "fetched_at": fetched_at}

    def _save_last_good(self, domain: str, key: str, method: str, payload: Any, provider: str) -> None:
        data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(domain, key).write_text(
                json.dumps(
                    {
                        "method": method,
                        "data": data,
                        "fetched_at": now_utc(),
                        "provider": provider,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
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
                self._last_outcome[domain] = meta
                self._save_last_good(domain, key, method, result, provider.name)
                return {"result": result, "meta": meta}
            except Exception as exc:  # noqa: BLE001 - the degradation chain must swallow Provider exceptions
                errors.append(f"{provider.name}: {type(exc).__name__}: {exc}")
                continue

        # All Providers failed → last-good cache (expired/undated entries are not served, #66)
        cached = self._load_last_good(domain, key, method)
        if cached is not None:
            data, cache_meta = cached
            self.degraded_domains.add(domain)
            meta = {
                "provider": cache_meta["provider"],
                "used_fallback": True,
                "from_cache": True,
                "degraded": True,
                "errors": errors,
            }
            self._last_outcome[domain] = meta
            return {
                "result": data,
                "meta": meta,
            }

        raise ProviderError(f"[{domain}] all Providers failed: {'; '.join(errors)}")

    def resolved_provider(self, domain: str) -> dict[str, Any] | None:
        """The provider outcome of the most recent successful call for `domain` (#65).

        Returns the meta (provider/used_fallback/from_cache/degraded) of the provider that
        actually answered, or ``None`` if nothing succeeded (or was served from cache).
        """
        return self._last_outcome.get(domain)

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
