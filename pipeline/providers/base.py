"""Provider abstraction and degradation chain (architecture §1.4, #91/#92/#103).

- BaseProvider: unified interface (health + per-domain methods); all external data must go through it.
- ProviderRegistry: domain → ordered Provider list + last-good cache + degraded markers.
- Degradation chain (must be implementable as test cases):
    primary Provider failure/timeout/rate limit → single retry layer (≤ degrade.max_retries)
    → fallback Provider → last-good cache → mark degraded, lower data_quality
    → all failed: freshness=missing, payload keeps last data + stale marker
- No Provider exception may interrupt the whole pipeline (Collector catches → degraded → continue).

#103 contracts:
- ``ProviderError`` carries a three-class taxonomy (transient / rate_limited / permanent;
  unclassified defaults to permanent). ``ProviderError.from_exception`` is the **one** error
  boundary: it classifies and runs every message through :func:`redact` (S-1).
- One retry layer lives in ``ProviderRegistry.call`` — the nested ``retry_with_backoff`` in
  individual providers is gone (E-3, max 3 attempts not 9).
- Per-(provider, host) circuit breaker: 3 consecutive *transient* failures open it;
  permanent failures do not count; a tripped breaker lets remaining symbols resolve through
  the fallback and the last-good cache, so it yields ``degraded``, never ``missing``.
- Per-host token bucket (``HostRateLimiter``) with per-provider ``max_concurrency`` /
  ``min_interval_ms`` from ``sources.yaml:providers`` — Yahoo carries the tightest budget.
  A ``rate_limited`` verdict trips the host limiter for the rest of the run.
- Cache trust (S-2): cache entries carry ``schema_version``; a version mismatch or a replay
  that fails model validation is quarantined as ``.corrupt`` and treated as a miss — never
  an error.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Semaphore
from typing import Any, Generator

import httpx
from pydantic import BaseModel, Field

from pipeline.degrade import degrade_factor as resolve_degrade_factor
from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.settings import Settings
from pipeline.utils import now_utc

logger = logging.getLogger(__name__)

# Default timeout/retry (overridable by config/sources.yaml degrade)
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 1.0

#: Error classes (one taxonomy, #103).
TRANSIENT = "transient"
RATE_LIMITED = "rate_limited"
PERMANENT = "permanent"
_RETRYABLE = frozenset({TRANSIENT, RATE_LIMITED})

#: Exception types treated as transient transport failures (worth a retry). Includes the
#: transport families actually in use: httpx, requests (yfinance's stack) and curl_cffi
#: (Yahoo via yfinance per #87). Built lazily because requests/curl_cffi are transitive
#: dependencies — a provider that never uses them must still import cleanly.
def _transient_types() -> tuple[type, ...]:
    base: tuple[type, ...] = (httpx.TransportError, httpx.TimeoutException, ConnectionError, TimeoutError, OSError)
    extras: list[type] = []
    try:
        import requests  # type: ignore[import-not-found]

        extras.append(requests.exceptions.RequestException)
    except ImportError:
        pass
    try:
        from curl_cffi import requests as _curl  # type: ignore[import-not-found]
        from curl_cffi.curl import CurlError as _CurlError  # type: ignore[import-not-found]

        extras.append(_curl.errors.RequestsError)
        extras.append(_CurlError)  # libcurl-level errors too
    except ImportError:
        pass
    return base + tuple(extras)


_TRANSIENT_TYPES: tuple[type, ...] = _transient_types()


def redact(text: str, max_len: int = 200) -> str:
    """The single redaction function (S-1/#92): strip URL query strings, mask key shapes,
    truncate. Every provider error message passes through this at the from_exception boundary,
    so an exception repr that embeds ``?api_key=...`` can never reach a published file.
    """
    s = str(text)
    # Strip the query string from any URL (drop everything after the first ? up to a boundary).
    s = re.sub(r"(https?://[^\s\"'<>()]+?)\?[^\s\"'<>()]*", r"\1", s)
    # Mask named key parameters (api_key=, apikey=, token=, key=).
    s = re.sub(r"(?i)([?&])(?:api[_-]?key|apikey|token|key)=[^&\s\"'<>]*", r"\1***=***", s)
    # Mask bare key-shaped tokens. Length-40 hex stays UNMASKED on purpose: the news
    # dedupe ids are sha1 and published everywhere. The word boundaries make the 32-char
    # rule safe against it anyway ({32} inside a 40-char run has no boundary at its end).
    s = re.sub(r"\b[0-9a-f]{32}\b", "***", s, flags=re.I)  # FMP/FRED: 32 lowercase hex
    # 32-char MIXED-CASE alnum (FMP-style keys are not always hex) — empirically NOT
    # masked before #189; the scan-secrets literal gate was the only thing catching it.
    s = re.sub(r"\b[A-Za-z0-9]{32}\b", "***", s)
    # CoinGecko demo keys travel with their CG- prefix.
    s = re.sub(r"\bCG-[A-Za-z0-9]{8,}\b", "CG-***", s, flags=re.I)
    s = re.sub(r"\b[a-zA-Z0-9]{36,64}\b", "***", s)
    return s[:max_len]


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    """Honour ``Retry-After`` (delay-seconds or RFC-7231 HTTP-date), capped at 30s (#103)."""
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        from email.utils import parsedate_to_datetime

        try:
            seconds = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return None
    if seconds <= 0 or seconds > 30:
        return None
    return seconds


#: S-3: outbound redirect guard bounds — https only, at most 3 hops per request, 2 MB cap.
MAX_REDIRECT_HOPS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class GuardedClient(httpx.Client):
    """An httpx client whose outbound requests are allowlisted **per hop** (S-3/#92).

    ``follow_redirects`` is disabled and redirects are walked manually (≤ :data:`MAX_REDIRECT_HOPS`),
    so every hop is checked against the allowlist and for https before its body is fetched.
    A response larger than 2 MB is refused. Used by every httpx-based provider instead of a
    bare ``httpx.Client``.
    """

    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        headers: dict[str, str] | None = None,
        relay_hosts: set[str] | None = None,
    ) -> None:
        super().__init__(
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
            event_hooks={"request": [self._check_request], "response": [self._check_response]},
        )
        self._allowed_hosts = set(allowed_hosts)
        # S-3 trust:relay — a hop redirected *from* a relay host is vouched for by the relay
        # and skips the allowlist check (rsshub.app's routes forward to arbitrary publishers).
        self._relay_hosts = set(relay_hosts or ())
        self._last_host: str | None = None

    def _check_request(self, request: httpx.Request) -> None:
        if request.url.scheme != "https":
            raise ProviderError(f"blocked: non-https outbound {request.url}")
        # A redirect source that is a relay vouches for the target host (S-3).
        if self._last_host in self._relay_hosts:
            self._last_host = request.url.host
            return
        if request.url.host not in self._allowed_hosts:
            raise ProviderError(f"blocked: host {request.url.host} not in outbound allowlist")
        self._last_host = request.url.host

    def _check_response(self, response: httpx.Response) -> None:
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            raise ProviderError(f"blocked: response exceeds {MAX_RESPONSE_BYTES} bytes ({response.url})")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """GET with a bounded manual redirect walk (≤ MAX_REDIRECT_HOPS hops) and a hard
        2 MB streaming cap — chunked bodies are bounded by reading, not by Content-Length."""
        from urllib.parse import urljoin

        for _ in range(MAX_REDIRECT_HOPS + 1):
            with super().stream("GET", url, **kwargs) as response:
                if response.status_code >= 300 and response.headers.get("location"):
                    url = urljoin(str(url), response.headers["location"])
                    continue
                return self._read_bounded(response)
        raise ProviderError(f"blocked: more than {MAX_REDIRECT_HOPS} redirect hops")

    def _read_bounded(self, response: httpx.Response) -> httpx.Response:
        """Read the body with a 2 MB cap (S-3); raise ProviderError past the cap."""
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ProviderError(f"blocked: response exceeds {MAX_RESPONSE_BYTES} bytes ({response.url})")
            chunks.append(chunk)
        response._content = b"".join(chunks)  # type: ignore[attr-defined]
        return response


def guarded_client(
    allowed_hosts: set[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    headers: dict[str, str] | None = None,
    relay_hosts: set[str] | None = None,
) -> "GuardedClient":
    """Factory for :class:`GuardedClient` (kept as a function so provider call sites stay terse)."""
    return GuardedClient(allowed_hosts, timeout=timeout, headers=headers, relay_hosts=relay_hosts)


class ProviderError(Exception):
    """Provider-layer error with a three-class taxonomy (#103).

    ``cls`` is one of :data:`TRANSIENT` / :data:`RATE_LIMITED` / :data:`PERMANENT`.
    Unclassified constructions default to ``PERMANENT`` — the safe direction: a failure we
    cannot prove is retryable must not be retried into a longer run.
    """

    def __init__(self, message: str, *, cls: str = PERMANENT, retry_after: float | None = None) -> None:
        super().__init__(redact(message))
        self.cls = cls
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        return self.cls in _RETRYABLE

    @classmethod
    def from_exception(cls, exc: BaseException, *, detail: str | None = None) -> "ProviderError":
        """The one error boundary (S-1): classify + redact a raw exception.

        ``detail`` (if given) replaces the exception's own string — providers use it to add
        symbol context; the redactor still strips any URL query / key shape from it.

        Transient covers the transport families in use: httpx, requests (yfinance), and
        curl_cffi (Yahoo via yfinance, #87) — a transport failure is by definition worth a
        retry, whatever the underlying HTTP library.
        """
        if isinstance(exc, ProviderError):
            return exc
        message = redact(detail if detail is not None else str(exc))
        kind = type(exc).__name__
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            status = response.status_code if response is not None else None
            if status == 429:
                return cls(f"{kind}: HTTP 429 rate limited", cls=RATE_LIMITED, retry_after=_retry_after_seconds(response))
            if status in {408, 425} or (status is not None and 500 <= status <= 599):
                return cls(f"{kind}: HTTP {status}", cls=TRANSIENT)
            return cls(f"{kind}: HTTP {status}", cls=PERMANENT)
        if isinstance(exc, _TRANSIENT_TYPES):
            return cls(f"{kind}: {message}", cls=TRANSIENT)
        return cls(f"{kind}: {message}", cls=PERMANENT)

    @classmethod
    def from_http(cls, prefix: str, response: httpx.Response) -> "ProviderError":
        """A non-200 httpx response, through the one boundary (S-1).

        The shared idiom every httpx provider uses for its status checks — one copy of the
        HTTPStatusError construction + classification instead of N (Duplicated Code, #94
        review). The 429/5xx/408/425 taxonomy lives in :meth:`from_exception`.
        """
        return cls.from_exception(
            httpx.HTTPStatusError(
                f"{prefix} HTTP {response.status_code}", request=response.request, response=response
            ),
            detail=f"{prefix} HTTP {response.status_code}",
        )


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
    priority: int = 100  # smaller number = higher priority; overridden per instance from config (#102)
    domain: str = "general"
    #: Host(s) this provider talks to, used as the per-host rate-limit bucket key (#103).
    #: Subclasses with dynamic hosts (RSS per-source) declare a synthetic bucket.
    hosts: tuple[str, ...] = ("general",)

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


class HostRateLimiter:
    """Per-host token bucket (#103/P-1): bounded concurrency + a minimum interval between
    calls to the same host. A ``rate_limited`` verdict trips the host for the rest of the run.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, Semaphore] = {}
        self._next_at: dict[str, float] = {}
        self._tripped: set[str] = set()

    @contextmanager
    def acquire(self, host: str, max_concurrency: int, min_interval_ms: int) -> Generator[None, None, None]:
        """Hold the host's concurrency slot while waiting out the minimum interval."""
        if host in self._tripped:
            raise ProviderError(f"host {host} rate-limited for the rest of the run", cls=RATE_LIMITED)
        semaphore = self._semaphores.setdefault(host, Semaphore(max_concurrency))
        with semaphore:
            wait = self._next_at.get(host, 0.0) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._next_at[host] = time.monotonic() + min_interval_ms / 1000.0
            yield

    def trip(self, host: str) -> None:
        self._tripped.add(host)

    def is_tripped(self, host: str) -> bool:
        return host in self._tripped


class CircuitBreaker:
    """Per-(provider, host-bucket) breaker: 3 **consecutive transient** failures open it; a
    permanent failure does not count; a success resets the streak (#103). A tripped breaker
    skips the provider for the rest of the run, letting fallbacks and the last-good cache
    answer — degraded, never missing.

    ``threshold`` comes from ``operations.circuit_breaker_threshold`` in sources.yaml (ADR
    0005: config is a fact), not a hardcoded literal.
    """

    def __init__(self, threshold: int = 3) -> None:
        self.threshold = threshold
        self._streak: dict[tuple[str, str], int] = {}
        self._open: set[tuple[str, str]] = set()

    @staticmethod
    def _key(provider: BaseProvider, host: str) -> tuple[str, str]:
        return (provider.name, host)

    def record_failure(self, provider: BaseProvider, host: str, error: ProviderError) -> None:
        key = self._key(provider, host)
        if error.cls == PERMANENT:
            self._streak.pop(key, None)  # permanent does not count toward the streak
            return
        streak = self._streak.get(key, 0) + 1
        self._streak[key] = streak
        if streak >= self.threshold:
            self._open.add(key)

    def record_success(self, provider: BaseProvider, host: str) -> None:
        key = self._key(provider, host)
        self._streak.pop(key, None)
        self._open.discard(key)

    def is_open(self, provider: BaseProvider, host: str) -> bool:
        return self._key(provider, host) in self._open


class ProviderRegistry:
    """Maintains the "domain → ordered Provider list" and the last-good cache (architecture §1.4)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        # #102: retries/backoff/jitter and the cache directory come from the VALIDATED
        # SourcesConfig.degrade, not the raw dict — a typo in the degrade block now fails
        # loudly at construction instead of silently falling back to a Python default.
        cfg = self.settings.load_sources_config()
        degrade = cfg.degrade
        self.max_retries = degrade.max_retries
        self.backoff_base = degrade.backoff_base_seconds
        self.jitter = degrade.jitter
        # Single source of truth (#62): pass the validated mapping so the accessor does not
        # re-read sources.yaml.
        self.degrade_factor = resolve_degrade_factor(sources=cfg.model_dump())
        # #102: the cache directory is config (`degrade.last_good_cache_dir`), resolved
        # against the project root when relative — it used to be hardcoded to
        # `artifacts/cache` here while the config key sat unused.
        cache_path = Path(degrade.last_good_cache_dir)
        self.cache_dir: Path = (
            cache_path if cache_path.is_absolute() else self.settings.project_root / cache_path
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._providers: dict[str, list[BaseProvider]] = {}
        self.health_map: dict[str, ProviderHealth] = {}
        self.degraded_domains: set[str] = set()
        #: Domain → meta of the most recent successful call (#65): the provider that answered.
        self._last_outcome: dict[str, dict[str, Any]] = {}
        # #103: per-provider host budgets from sources.yaml:providers (name → (concurrency, interval_ms)).
        self._host_budgets: dict[str, tuple[int, int]] = {
            entry.name: (entry.max_concurrency, entry.min_interval_ms)
            for entries in cfg.providers.values()
            for entry in entries
        }
        self.limiter = HostRateLimiter()
        # ADR 0005: the breaker threshold is config (operations.circuit_breaker_threshold),
        # not a second literal that can drift from sources.yaml.
        self.breaker = CircuitBreaker(threshold=cfg.operations.circuit_breaker_threshold)

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

    def _quarantine(self, path: Path) -> None:
        """Rename a corrupt/version-mismatched cache entry to ``.corrupt`` (S-2)."""
        try:
            path.rename(path.with_name(path.name + ".corrupt"))
        except OSError:
            logger.warning("could not quarantine corrupt cache entry %s", path)

    def _load_last_good(self, domain: str, key: str, method: str) -> tuple[Any, dict[str, Any]] | None:
        """Load a valid last-good cache entry, or ``None`` when it cannot be served (#66, S-2).

        A cache entry is served only when it is dated, younger than
        ``degrade.cache_max_age_hours``, carries the current ``schema_version``, and replays
        through the same model as a live response. Any failure is a **miss** (the caller
        reports ``cache_invalid``/``missing``), and an entry that fails version/validation is
        quarantined as ``.corrupt`` — never served, never silently ignored. Ruling C: an
        undated entry (the pre-#66 disk format) is beyond the maximum age.
        """
        from pipeline.degrade import cache_max_age_hours

        path = self._cache_path(domain, key)
        if not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._quarantine(path)
            return None
        if not isinstance(cached, dict):
            self._quarantine(path)
            return None
        # S-2: a version mismatch is a miss, and the entry is quarantined (a new pipeline
        # must not replay results serialized under an older contract).
        if cached.get("schema_version") != SCHEMA_VERSION:
            self._quarantine(path)
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
            except Exception:  # noqa: BLE001 - a replay that fails validation is a miss, not an error
                self._quarantine(path)
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
                        "schema_version": SCHEMA_VERSION,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # E-4: a cache-write failure is logged, not silently swallowed
            logger.warning("cache write failed (%s__%s): %s", domain, key, exc)

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
        The **single** retry layer (#103/E-3), the per-host limiter and the per-(provider,
        host) circuit breaker all live here. When every provider fails: try the last-good
        cache → still fail raises ProviderError. A tripped breaker skips the provider (so
        remaining symbols resolve through fallback/cache — degraded, never missing).
        """
        kwargs = kwargs or {}
        providers = self.providers_for(domain)
        errors: list[str] = []

        for index, provider in enumerate(providers):
            host = self._host_for(provider)
            if self.breaker.is_open(provider, host):
                errors.append(f"{provider.name}: circuit open ({host})")
                self.degraded_domains.add(domain)
                continue
            try:
                result = self._attempt(provider, method, args, kwargs, host)
                meta = {
                    "provider": provider.name,
                    "used_fallback": index > 0,
                    "from_cache": False,
                    "degraded": index > 0,
                }
                self.breaker.record_success(provider, host)
                if index > 0:
                    self.degraded_domains.add(domain)
                self._last_outcome[domain] = meta
                self._save_last_good(domain, key, method, result, provider.name)
                return {"result": result, "meta": meta}
            except ProviderError as exc:
                self.breaker.record_failure(provider, host, exc)
                if exc.cls == RATE_LIMITED:
                    # A rate-limited verdict trips the host limiter for the rest of the run (#103).
                    self.limiter.trip(host)
                errors.append(f"{provider.name}: {redact(str(exc))}")
                continue

        # All Providers failed → last-good cache (expired/undated/version-mismatched entries
        # are not served, #66/S-2)
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

    def _host_for(self, provider: BaseProvider) -> str:
        return provider.hosts[0] if provider.hosts else "general"

    def _attempt(self, provider: BaseProvider, method: str, args: tuple, kwargs: dict[str, Any], host: str) -> Any:
        """One provider call with the single retry layer (#103/E-3).

        Max ``degrade.max_retries`` retries (so 3 attempts total, not 9). A permanent error
        is not retried; ``rate_limited`` honours ``Retry-After``; transient errors back off
        exponentially with jitter. The host limiter is held across every attempt. A host that
        was tripped by an earlier rate-limited verdict short-circuits **before** the retry
        loop — it is not retried with backoff.
        """
        if self.limiter.is_tripped(host):
            raise ProviderError(f"host {host} rate-limited for the rest of the run", cls=RATE_LIMITED)
        max_concurrency, min_interval_ms = self._host_budgets.get(provider.name, (2, 500))
        max_attempts = self.max_retries + 1
        attempt = 0
        while True:
            attempt += 1
            try:
                with self.limiter.acquire(host, max_concurrency, min_interval_ms):
                    return getattr(provider, method)(*args, **kwargs)
            except ProviderError as exc:
                last = exc
            except Exception as exc:  # noqa: BLE001 - classify at the one boundary
                last = ProviderError.from_exception(exc)
            if attempt >= max_attempts or not last.transient:
                raise last
            time.sleep(self._backoff(last, attempt))

    def _backoff(self, error: ProviderError, attempt: int) -> float:
        if error.cls == RATE_LIMITED:
            if error.retry_after:
                return error.retry_after
            return self.backoff_base * (4**attempt)
        delay = self.backoff_base * (2 ** (attempt - 1))
        return delay * (0.5 + random.random()) if self.jitter else delay

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


