"""FMP stable earnings-calendar parsing (#94/#83): /stable namespace, renamed fields."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pipeline.providers.base import ProviderError
from pipeline.providers.fmp import EARNINGS_ENDPOINT, FmpProvider
from pipeline.settings import Settings


def _provider(tmp_path: Path) -> FmpProvider:
    settings = Settings(_env_file=None)
    provider = FmpProvider(settings)
    provider.api_key = "test-key"  # tests never touch the real .env
    return provider


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", "https://financialmodelingprep.com/stable/earnings-calendar")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict) -> Any:
        self.calls.append((url, params))
        return self._responses.pop(0)


def test_stable_endpoint_and_renamed_fields(tmp_path: Path) -> None:
    """#83: the 403 fix is a namespace move — /stable/earnings-calendar, and the stable
    payload renames `eps` → `epsActual` (reading the old key would silently produce None)."""
    client = _Client([
        _Resp(200, [
            {
                "symbol": "RKT",
                "date": "2026-08-06",
                "epsActual": 0.35,
                "epsEstimated": 0.1642,
                "revenueActual": 3100000000,
                "revenueEstimated": 2811788000,
                "lastUpdated": "2026-08-06",
            }
        ]),
    ])
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider.get_earnings_calendar("2026-08-01", "2026-08-14")

    url, params = client.calls[0]
    assert url == EARNINGS_ENDPOINT and "api/v3" not in url
    assert params["from"] == "2026-08-01" and params["apikey"] == "test-key"
    assert rows[0]["symbol"] == "RKT"
    assert rows[0]["eps_actual"] == 0.35
    assert rows[0]["eps_estimate"] == 0.1642
    assert rows[0]["revenue_actual"] == 3100000000
    assert rows[0]["revenue_estimate"] == 2811788000
    # stable dropped `time` — the session is honestly None (Nasdaq restores it).
    assert rows[0]["session"] is None


def test_legacy_eps_key_is_ignored(tmp_path: Path) -> None:
    """A stray legacy `eps` key must NOT populate eps_actual (the silent-corruption trap)."""
    client = _Client([_Resp(200, [{"symbol": "AAPL", "date": "2026-08-06", "eps": 9.99}])])
    provider = _provider(tmp_path)
    provider._client = client
    rows = provider.get_earnings_calendar("2026-08-01", "2026-08-14")
    assert rows[0]["eps_actual"] is None


def test_http_error_classified_as_permanent(tmp_path: Path) -> None:
    """A 403/500 must raise ProviderError through the one boundary (S-1), not a raw httpx error."""
    client = _Client([_Resp(403)])
    provider = _provider(tmp_path)
    provider._client = client
    with pytest.raises(ProviderError, match="HTTP 403"):
        provider.get_earnings_calendar("2026-08-01", "2026-08-14")


def test_malformed_row_is_skipped(tmp_path: Path) -> None:
    client = _Client([_Resp(200, [{"symbol": "", "date": "2026-08-06"}, {"symbol": "MSFT", "date": ""}, {"symbol": "NVDA", "date": "2026-08-12", "epsActual": 0.8}])])
    provider = _provider(tmp_path)
    provider._client = client
    rows = provider.get_earnings_calendar("2026-08-01", "2026-08-14")
    assert [r["symbol"] for r in rows] == ["NVDA"]
