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

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from pipeline.providers.base import (
    MAX_RESPONSE_BYTES,
    PERMANENT,
    RATE_LIMITED,
    TRANSIENT,
    GuardedClient,
    CircuitBreaker,
    HostRateLimiter,
    NewsRow,
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


def test_redact_masks_fmp_and_coingecko_key_shapes() -> None:
    """Synthetic shapes only — never a real key (#189).

    A 32-char mixed-case alnum token (FMP style is not always hex) and a CG- prefixed
    demo key were empirically NOT masked before #189; the scan-secrets literal gate was
    the only thing standing between them and a published file.
    """
    fmp_style = "aB3dEf7hIj9kLmN0pQr5tUv8wXyZ1234"  # 32 mixed-case alnum, synthetic
    assert fmp_style not in redact("history fetch failed for " + fmp_style)
    assert "***" in redact("history fetch failed for " + fmp_style)

    cg_key = "CG-" + "zK9pQ2mX7vB4nR8t"  # CoinGecko demo shape, synthetic
    assert cg_key not in redact("coingecko error: key " + cg_key)
    assert "CG-***" in redact("coingecko error: key " + cg_key)

    # Boundary precision: a 35-char token sits between the two windows ({32} has no
    # end-boundary mid-run; {36,64} starts at 36), so it survives - proof the new rule
    # masks exactly its window, not everything around it.
    tok35 = "a" * 17 + "B" * 18
    assert tok35 in redact("token " + tok35)

    # A 40-hex run is INSIDE the pre-existing deliberate 36-64 mask window (any 36-64
    # alnum token reads as a long credential in free text). Dedupe ids never travel
    # through provider error text, so nothing published loses its id.
    sha1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    assert sha1 not in redact("weird payload " + sha1)


def test_news_replay_row_rejects_unsafe_article_url() -> None:
    with pytest.raises(ValueError, match="news URL"):
        NewsRow(title="headline", source="source", source_id="source", url="javascript:alert(1)", published_at="2026-08-03T00:00:00Z")


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


def test_transport_errors_from_requests_and_curl_cffi_are_transient() -> None:
    """yfinance talks to Yahoo through requests/curl_cffi — those transport errors must be
    classified transient, or the primary quotes provider would never retry (spec finding)."""
    import requests
    from curl_cffi import requests as curl

    assert ProviderError.from_exception(requests.exceptions.Timeout()).cls == TRANSIENT
    assert ProviderError.from_exception(requests.exceptions.ConnectionError()).cls == TRANSIENT
    # curl_cffi's CurlError is the base of its request errors (timeouts etc.).
    assert ProviderError.from_exception(curl.errors.CurlError("boom")).cls == TRANSIENT


def test_key_bearing_http_error_never_reaches_the_caller(tmp_path: Path) -> None:
    """S-1: a key-bearing HTTPStatusError raised by a provider must be redacted before it
    reaches the caller — the same shape as an exception repr embedding ``?apikey=…``."""
    provider = _FakeProvider()
    key = "0123456789abcdef0123456789abcdef"
    request = httpx.Request("GET", f"https://api.fmp.example/calendar?apikey={key}")
    provider.results = [
        httpx.HTTPStatusError("403", request=request, response=httpx.Response(403, request=request))
    ]
    registry = _registry(tmp_path, provider)
    registry.max_retries = 0

    with pytest.raises(ProviderError) as excinfo:
        registry.call("test", "get_quote", "q1", args=("SYM",))
    assert key not in str(excinfo.value)
    assert "apikey" not in str(excinfo.value)


def test_guarded_client_decodes_gzipped_response() -> None:
    """Regression (2026-08-24, #103 carry-forward): GuardedClient.get must auto-decode a
    gzipped body. The streaming ``iter_bytes`` path in httpx 0.28.x raised
    ``DecodingError: incorrect header check`` on gzipped responses, which emptied every
    HTTP-JSON dataset (fred/coingecko/calendar/news). The bounded streaming request decodes it."""
    import gzip

    payload = b'{"observations": [{"date": "2026-01-01", "value": "1.23"}]}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(payload),
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            request=request,
        )

    client = GuardedClient({"api.stlouisfed.org"}, transport=httpx.MockTransport(handler))
    try:
        resp = client.get("https://api.stlouisfed.org/fred/series/observations")
        assert resp.status_code == 200
        assert resp.json() == {"observations": [{"date": "2026-01-01", "value": "1.23"}]}
    finally:
        client.close()


@pytest.mark.parametrize("encoding", ["deflate", "br"])
def test_guarded_client_decodes_other_supported_content_encodings(encoding: str) -> None:
    import zlib

    import brotli

    payload = b'{"value": "decoded"}'
    compressed = zlib.compress(payload) if encoding == "deflate" else brotli.compress(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=compressed,
            headers={"Content-Encoding": encoding, "Content-Type": "application/json"},
            request=request,
        )

    client = GuardedClient({"api.example"}, transport=httpx.MockTransport(handler))
    try:
        assert client.get("https://api.example/data").json() == {"value": "decoded"}
    finally:
        client.close()


class _TrackingStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


def test_guarded_client_rejects_declared_oversize_and_closes_response() -> None:
    stream = _TrackingStream(b"ok")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
            stream=stream,
            request=request,
        )

    client = GuardedClient({"api.example"}, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="response exceeds"):
            client.get("https://api.example/data")
        assert stream.closed
    finally:
        client.close()


def test_guarded_client_rejects_unknown_length_oversize_and_closes_response() -> None:
    stream = _TrackingStream(b"x" * (MAX_RESPONSE_BYTES + 1))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, request=request)

    client = GuardedClient({"api.example"}, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="response exceeds"):
            client.get("https://api.example/data")
        assert stream.closed
    finally:
        client.close()


def test_guarded_client_rejects_decoded_gzip_oversize() -> None:
    import gzip

    compressed = gzip.compress(b"x" * (MAX_RESPONSE_BYTES + 1))
    assert len(compressed) < MAX_RESPONSE_BYTES

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=compressed,
            headers={"Content-Encoding": "gzip"},
            request=request,
        )

    client = GuardedClient({"api.example"}, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderError, match="response exceeds"):
            client.get("https://api.example/data")
    finally:
        client.close()


def test_guarded_client_rejects_oversize_redirect_target() -> None:
    stream = _TrackingStream(b"x" * (MAX_RESPONSE_BYTES + 1))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "relay.example":
            return httpx.Response(
                302,
                headers={"location": "https://publisher.example/data"},
                request=request,
            )
        return httpx.Response(200, stream=stream, request=request)

    client = GuardedClient(
        {"relay.example", "publisher.example"}, transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ProviderError, match="response exceeds"):
            client.get("https://relay.example/data")
        assert stream.closed
    finally:
        client.close()


def test_redirect_relay_voucher_is_scoped_to_one_request() -> None:
    """A relay may vouch for its redirect target without leaking trust to another GET."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "relay.example":
            return httpx.Response(302, headers={"location": "https://publisher.example/feed"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    client = GuardedClient(
        {"relay.example"},
        relay_hosts={"relay.example"},
        relay_target_hosts={"publisher.example"},
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.get("https://relay.example/feed").text == "ok"
        with pytest.raises(ProviderError, match="not in outbound allowlist"):
            client.get("https://blocked.example/feed")
        with pytest.raises(ProviderError, match="not in outbound allowlist"):
            client.get("https://blocked.example/feed", extensions={"relay_vouched": True})
    finally:
        client.close()


def test_relay_voucher_rejects_unlisted_target() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://blocked.example/feed"},
            request=request,
        )

    client = GuardedClient(
        {"relay.example"},
        relay_hosts={"relay.example"},
        relay_target_hosts={"publisher.example"},
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ProviderError, match="relay target"):
            client.get("https://relay.example/feed")
    finally:
        client.close()


def test_guarded_client_rejects_non_public_ip_even_when_allowlisted() -> None:
    client = GuardedClient({"127.0.0.1"}, transport=httpx.MockTransport(lambda request: None))
    try:
        with pytest.raises(ProviderError, match="non-public outbound IP"):
            client.get("https://127.0.0.1/feed")
    finally:
        client.close()


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


def test_circuit_breaker_counts_concurrent_failures_without_lost_updates() -> None:
    provider = _FakeProvider()
    breaker = CircuitBreaker(threshold=100)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda _: breaker.record_failure(
                    provider, "fake.example", ProviderError("transient", cls=TRANSIENT)
                ),
                range(100),
            )
        )

    assert breaker._streak[(provider.name, "fake.example")] == 100
    assert breaker.is_open(provider, "fake.example")


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


def test_host_rate_limiter_serializes_concurrent_interval_reservations() -> None:
    limiter = HostRateLimiter()
    starts: list[float] = []

    def call() -> None:
        with limiter.acquire("fake.example", max_concurrency=8, min_interval_ms=5):
            starts.append(time.monotonic())

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: call(), range(8)))

    ordered = sorted(starts)
    assert len(ordered) == 8
    assert all(later - earlier >= 0.003 for earlier, later in zip(ordered, ordered[1:]))


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


def test_future_cache_timestamp_is_quarantined_miss(tmp_path: Path) -> None:
    registry = _registry(tmp_path, _FakeProvider())
    path = registry._cache_path("test", "q_future")
    path.write_text(
        json.dumps(
            {
                "method": "get_quote",
                "data": {"symbol": "SYM", "price": 2.0},
                "fetched_at": "2999-01-01T00:00:00Z",
                "provider": "fake",
                "schema_version": "1.1.0",
            }
        ),
        encoding="utf-8",
    )

    assert registry._load_last_good("test", "q_future", "get_quote") is None
    assert not path.exists()
    assert path.with_name(path.name + ".corrupt").exists()


@pytest.mark.parametrize(
    ("method", "data"),
    [
        ("get_earnings_calendar", [{"date": "2026-08-06"}]),
        ("get_economic_calendar", [{"id": "econ-1", "title": "CPI"}]),
        ("fetch_news", [{"title": "headline"}]),
        ("get_crypto_market", {"assets": [{"price": 100.0}]}),
    ],
)
def test_corrupt_parseable_domain_cache_is_quarantined(
    tmp_path: Path, method: str, data: object
) -> None:
    registry = _registry(tmp_path, _FakeProvider())
    path = registry._cache_path("test", method)
    path.write_text(
        json.dumps(
            {
                "method": method,
                "data": data,
                "fetched_at": now_utc(),
                "provider": "fake",
                "schema_version": "1.1.0",
            }
        ),
        encoding="utf-8",
    )

    assert registry._load_last_good("test", method, method) is None
    assert path.with_name(path.name + ".corrupt").exists()
