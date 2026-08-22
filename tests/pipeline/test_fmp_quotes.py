"""FMP quotes fallback (#100): /stable/quote parsing and the fallback-selection liveness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pipeline.providers.base import ProviderError
from pipeline.providers.fallback_health import check_fallbacks, fallback_providers
from pipeline.providers.fmp import FMP_BASE, FmpQuotesProvider
from pipeline.settings import Settings


def _provider(tmp_path: Path) -> FmpQuotesProvider:
    provider = FmpQuotesProvider(Settings(_env_file=None))
    provider.api_key = "test-key"
    return provider


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", f"{FMP_BASE}/quote")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict) -> Any:
        self.calls.append((url, params))
        return self._responses.pop(0)


def test_quote_parsing_and_endpoint(tmp_path: Path) -> None:
    client = _Client([_Resp(200, [{"symbol": "SPY", "price": 768.56, "changePercentage": -0.15978,
                                   "change": -1.23, "volume": 33043052, "dayLow": 767.46, "dayHigh": 771.82}])])
    provider = _provider(tmp_path)
    provider._client = client

    quote = provider.get_quote("SPY")

    url, params = client.calls[0]
    assert url == f"{FMP_BASE}/quote" and "api/v3" not in url
    assert params["symbol"] == "SPY" and params["apikey"] == "test-key"
    assert quote.price == pytest.approx(768.56)
    assert quote.change_1d == pytest.approx(-0.15978)
    assert quote.volume == 33043052
    assert quote.source == "fmp"
    # The free tier carries no 1w/1m/history — honest None, not fabricated (#100).
    assert quote.change_1w is None and quote.change_1m is None


def test_quote_missing_key_fails_fast(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.api_key = ""
    with pytest.raises(ProviderError, match="DATA_FMP_API_KEY"):
        provider.get_quote("SPY")


def test_quote_bad_payload_raises(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider._client = _Client([_Resp(200, [])])
    with pytest.raises(ProviderError, match="unexpected payload"):
        provider.get_quote("SPY")


class _FakeProvider:
    def __init__(self, name: str, domain: str, priority: int, ok: bool = True) -> None:
        self.name = name
        self.domain = domain
        self.priority = priority
        self._ok = ok

    def health(self):
        from pipeline.providers.base import ProviderHealth

        return ProviderHealth(provider=self.name, ok=self._ok, error=None if self._ok else "dead", checked_at=None)


def test_fallback_selection_uses_priority_not_kind() -> None:
    """A fallback is any provider above the domain's minimum priority — `kind` labels are
    descriptive (#100 DoD 3: the providers block is the real registry)."""
    providers = [
        _FakeProvider("yfinance", "quotes", 1),
        _FakeProvider("fmp_quotes", "quotes", 2),
        _FakeProvider("fred", "macro", 1),
        _FakeProvider("rss_news", "news", 1),
        _FakeProvider("yfinance_a_share", "a_share", 1),
        _FakeProvider("akshare", "a_share", 2),
    ]
    fallbacks = fallback_providers(providers)  # type: ignore[arg-type]
    assert sorted(f.name for f in fallbacks) == ["akshare", "fmp_quotes"]


def test_check_fallbacks_reports_dead_fallbacks() -> None:
    providers = [
        _FakeProvider("yfinance", "quotes", 1),
        _FakeProvider("fmp_quotes", "quotes", 2, ok=False),
        _FakeProvider("fred", "macro", 1),
        _FakeProvider("fred_calendar", "economic", 1),
    ]
    result = check_fallbacks(providers)  # type: ignore[arg-type]
    assert len(result.probes) == 1
    assert result.probes[0].provider == "fmp_quotes"
    assert result.probes[0].status == "dead"
    assert [p.provider for p in result.dead] == ["fmp_quotes"]


def test_key_gated_fallback_without_key_is_skipped_not_failed() -> None:
    """#100 review: a credential-gated fallback with no credential is SKIPPED — a
    permanently red scheduled job becomes ignored noise, the exact rot this check
    exists to prevent. Its real liveness is exercised by the daily pipeline run."""

    class _KeyedFake(_FakeProvider):
        # Real key-gated providers use None when the environment is unset.
        requires_api_key = True
        api_key = None

    providers = [
        _FakeProvider("yfinance", "quotes", 1),
        _KeyedFake("fmp_quotes", "quotes", 2),
    ]
    result = check_fallbacks(providers)  # type: ignore[arg-type]
    assert result.probes[0].status == "skipped"
    assert result.dead == []
    assert "SKIPPED" in (result.probes[0].note or "")
