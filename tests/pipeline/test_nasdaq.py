"""Nasdaq earnings fallback parsing (#94): per-date fetch, session mapping, $-strings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pipeline.providers.base import ProviderError
from pipeline.providers.nasdaq import NASDAQ_EARNINGS, NasdaqCalendarProvider
from pipeline.settings import Settings


def _provider(tmp_path: Path) -> NasdaqCalendarProvider:
    provider = NasdaqCalendarProvider(Settings(_env_file=None))
    return provider


class _Resp:
    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.request = httpx.Request("GET", "https://api.nasdaq.com/api/calendar/earnings")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict) -> Any:
        self.calls.append((url, params))
        return self._responses.pop(0)


def _earnings_payload(rows: list[dict]) -> dict:
    return {"data": {"rows": rows}}


def test_per_date_fetch_and_session_mapping(tmp_path: Path) -> None:
    """#83 §3E: time-pre-market → BMO, time-after-hours → AMC, not-supplied → None."""
    client = _Client([
        _Resp(200, _earnings_payload([
            {"symbol": "CSCO", "name": "Cisco", "time": "time-not-supplied", "epsForecast": "$0.99"},
        ])),
        _Resp(200, _earnings_payload([
            {"symbol": "AAPL", "name": "Apple", "time": "time-pre-market", "epsForecast": "$2.31"},
            {"symbol": "MSFT", "name": "Microsoft", "time": "time-after-hours", "epsForecast": " "},
        ])),
    ])
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider.get_earnings_calendar("2026-08-01", "2026-08-02")

    assert [c[0] for c in client.calls] == [NASDAQ_EARNINGS, NASDAQ_EARNINGS]
    assert [c[1]["date"] for c in client.calls] == ["2026-08-01", "2026-08-02"]
    by_symbol = {r["symbol"]: r for r in rows}
    assert by_symbol["CSCO"]["session"] is None
    assert by_symbol["AAPL"]["session"] == "BMO"
    assert by_symbol["MSFT"]["session"] == "AMC"
    assert by_symbol["AAPL"]["eps_estimate"] == 2.31
    assert by_symbol["MSFT"]["eps_estimate"] is None  # " " (blank) → None, not a crash


def test_null_data_guard(tmp_path: Path) -> None:
    """`data` is sometimes null — must be a miss, not a TypeError (#83)."""
    client = _Client([_Resp(200, {"data": None})])
    provider = _provider(tmp_path)
    provider._client = client
    assert provider.get_earnings_calendar("2026-08-01", "2026-08-01") == []


def test_http_error_raises(tmp_path: Path) -> None:
    client = _Client([_Resp(500)])
    provider = _provider(tmp_path)
    provider._client = client
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.get_earnings_calendar("2026-08-01", "2026-08-01")


def test_reversed_window_returns_empty(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider._client = _Client([])
    assert provider.get_earnings_calendar("2026-08-10", "2026-08-01") == []
