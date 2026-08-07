"""#103 provider-layer tests: error taxonomy + redaction, one retry layer, circuit breaker,
per-host limiter, cache trust.

Pins the contracts the ticket installs (E-3, S-1, S-2, #91/#92):
- ``ProviderError.from_exception`` is the one error boundary: it classifies
  (transient/rate_limited/permanent) and runs every message through ``redact``.
- Retries live ONLY in ``ProviderRegistry.call`` (max 3 attempts, not 9).
- The per-(provider, host) breaker opens after 3 consecutive *transient* failures and
  yields degraded (fallback/cache), never missing.
- A rate-limited verdict trips the host limiter for the rest of the run.
- Cache entries carry ``schema_version``; a mismatch is quarantined as ``.corrupt`` and is
  a miss, never an error.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pipeline.providers.base import (
    PERMANENT,
    RATE_LIMITED,
    TRANSIENT,
    ProviderError,
    ProviderHealth,
    ProviderRegistry,
    QuoteResult,
    redact,
)
from pipeline.settings import Settings
from pipeline.utils import now_utc


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, artifacts_dir=tmp_path, data_dir=tmp_path / "data")


# -------------------------------------------------------------------------------------
# redact() (S-1)
# -------------------------------------------------------------------------------------


def test_redact_strips_url_queries_and_masks_key_shapes() -> None:
    assert redact("GET https://api.fred.org/series?api_key=abc123def456&x=1 failed") == (
        "GET https://api.fred.org/series failed"
    )
    assert "secret" not in redact("apikey=deadbeefdeadbeefdeadbeefdeadbeef")
    assert "deadbeef" not in redact("token=deadbeefdeadbeefdeadbeefdeadbeef")
    long = "x" * 500
    assert len(redact(long)) == 200


def test_from_exception_classifies_and_redacts_http_errors() -> None:
    request = httpx.Request("GET", "https://api.fmp.example/calendar?apikey=0123456789abcdef0123456789abcdef")
    response = httpx.Response(429, request=request, headers={"Retry-After": "5"})
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)
    err = ProviderError.from_exception(exc)
    assert err.cls == RATE_LIMITED
    assert err.retry_after == 5.0
    assert "0123456789abcdef" not in str(err)  # the URL's query was stripped

    err500 = ProviderError.from_exception(
        httpx.HTTPStatusError("boom", request=request, response=httpx.Response(503, request=request))
    )
    assert err500.cls == TRANSIENT

    err404 = ProviderError.from_exception(
        httpx.HTTPStatusError("gone", request=request, response=httpx.Response(404, request=request))
    )
    assert err404.cls == PERMANENT


def test_from_exception_unclassified_defaults_to_permanent() -> None:
    err = ProviderError("plain failure")
    assert err.cls == PERMANENT
    assert err.transient is False


# -------------------------------------------------------------------------------------
# One retry layer in ProviderRegistry.call (E-3)
# -------------------------------------------------------------------------------------


class _FakeProvider:
    """Minimal provider-like object (no BaseProvider ceremony) for registry tests."""

    name = "fake"
    domain = "test"
    priority = 100
    hosts = ("fake.example",)
    health = lambda self: ProviderHealth(provider="fake", ok=True)  # noqa: E731

    def __init__(self) -> None:
        self.calls = 0
        self.results: list[object] = []

    def get_quote(self, symbol: str) -> QuoteResult:
        self.calls += 1
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return QuoteResult(symbol=symbol, price=1.0, source="fake", provider="fake", updated_at=now_utc())


def _registry(tmp_path: Path, provider: _FakeProvider) -> ProviderRegistry:
    registry = ProviderRegistry(_settings(tmp_path))
    registry.max_retries = 2  # 3 attempts total
    registry.backoff_base = 0.0
    registry.jitter = False
    # #103: the registry resolves its cache dir from sources.yaml (project-rooted). Tests pin
    # it to their own tmp_path so cache entries cannot leak across tests via the shared repo
    # artifacts/cache.
    registry.cache_dir = tmp_path / "cache"
    registry.cache_dir.mkdir(parents=True, exist_ok=True)
    registry.register(provider.domain, provider)
    return registry


def test_registry_retries_transient_then_succeeds(tmp_path: Path) -> None:
    provider = _FakeProvider()
    provider.results = [ProviderError("flake", cls=TRANSIENT), ProviderError("flake", cls=TRANSIENT)]
    registry = _registry(tmp_path, provider)

    out = registry.call("test", "get_quote", "q1", args=("SYM",))
    assert out["meta"]["provider"] == "fake"
    assert provider.calls == 3  # 2 retries + 1 initial


def test_registry_does_not_retry_permanent_errors(tmp_path: Path) -> None:
    provider = _FakeProvider()
    provider.results = [ProviderError("nope", cls=PERMANENT)]
    registry = _registry(tmp_path, provider)

    with pytest.raises(ProviderError, match="all Providers failed"):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    assert provider.calls == 1  # permanent → no retry


# -------------------------------------------------------------------------------------
# Circuit breaker: 3 consecutive transient failures → open → degraded not missing
# -------------------------------------------------------------------------------------


def test_circuit_breaker_opens_after_three_transient_failures(tmp_path: Path) -> None:
    provider = _FakeProvider()
    provider.results = [ProviderError("t1", cls=TRANSIENT)] * 100  # always transient
    registry = _registry(tmp_path, provider)

    for _ in range(3):
        with pytest.raises(ProviderError):
            registry.call("test", "get_quote", "q1", args=("SYM",))

    # The breaker is open: the provider is skipped (no further network), the domain is
    # marked degraded, and the call still raises — degraded, not missing.
    calls_before = provider.calls
    with pytest.raises(ProviderError, match="circuit open"):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    assert provider.calls == calls_before
    assert "test" in registry.degraded_domains


def test_circuit_breaker_permanent_failures_do_not_count(tmp_path: Path) -> None:
    provider = _FakeProvider()
    provider.results = [ProviderError("perm", cls=PERMANENT)] * 100
    registry = _registry(tmp_path, provider)

    for _ in range(5):
        with pytest.raises(ProviderError):
            registry.call("test", "get_quote", "q1", args=("SYM",))
    assert registry.breaker.is_open(provider, "fake.example") is False


def test_circuit_breaker_success_resets_the_streak(tmp_path: Path) -> None:
    provider = _FakeProvider()
    registry = _registry(tmp_path, provider)
    registry.max_retries = 0  # one attempt per call, so each transient is one failed call
    # two transient failures, then a success — the breaker must not trip.
    provider.results = [
        ProviderError("t1", cls=TRANSIENT),
        ProviderError("t2", cls=TRANSIENT),
    ]
    with pytest.raises(ProviderError):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    with pytest.raises(ProviderError):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    out = registry.call("test", "get_quote", "q1", args=("SYM",))
    assert out["result"].symbol == "SYM"
    assert registry.breaker.is_open(provider, "fake.example") is False


# -------------------------------------------------------------------------------------
# Rate-limited verdict trips the host limiter (rest of the run)
# -------------------------------------------------------------------------------------


def test_rate_limited_trips_the_host_limiter(tmp_path: Path) -> None:
    provider = _FakeProvider()
    provider.results = [ProviderError("429", cls=RATE_LIMITED)]
    registry = _registry(tmp_path, provider)
    registry.max_retries = 0

    with pytest.raises(ProviderError):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    assert registry.limiter.is_tripped("fake.example")

    calls_before = provider.calls
    with pytest.raises(ProviderError, match="rate-limited for the rest of the run"):
        registry.call("test", "get_quote", "q1", args=("SYM",))
    assert provider.calls == calls_before  # the limiter blocked before the provider ran


# -------------------------------------------------------------------------------------
# Cache trust (S-2): schema_version mismatch is a quarantined miss
# -------------------------------------------------------------------------------------


def test_cache_version_mismatch_is_quarantined_miss(tmp_path: Path) -> None:
    provider = _FakeProvider()
    registry = _registry(tmp_path, provider)

    quote = QuoteResult(symbol="SYM", price=2.0, source="fake", provider="fake", updated_at=now_utc())
    registry._save_last_good("test", "q_old", "get_quote", quote, "fake")

    # Simulate a cache entry written under an older schema version.
    path = registry._cache_path("test", "q_old")
    text = path.read_text(encoding="utf-8").replace('"schema_version": "1.1.0"', '"schema_version": "0.9.0"')
    path.write_text(text, encoding="utf-8")

    # Replay is a miss, and the entry is quarantined.
    provider.results = [ProviderError("gone", cls=PERMANENT)]
    with pytest.raises(ProviderError, match="all Providers failed"):
        registry.call("test", "get_quote", "q_old", args=("SYM",))
    assert not path.exists()
    assert path.with_name(path.name + ".corrupt").exists()
