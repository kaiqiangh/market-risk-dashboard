"""Earnings calendar fallback: Nasdaq's unofficial calendar endpoint (#94, source B of #83).

Chosen in #83 as the earnings fallback: no API key, and it restores the BMO/AMC session
signal that FMP's stable payload dropped. Per-date endpoint → one GET per day in the
window (≤ `calendar_horizon_days` calls, only when FMP is down). No stable event id —
the dedupe key is the shared `earnings-{symbol}-{date}` the collector builds from the
normalized row, identical to FMP's, so a run that somehow saw both sources would dedupe.

Fragility is accepted and bounded: the endpoint is undocumented and licence-grey, so this
is a *fallback only*; FMP remains the primary and its failure still degrades the domain.
"""

from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from pipeline.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderHealth,
)

NASDAQ_EARNINGS = "https://api.nasdaq.com/api/calendar/earnings"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

#: Nasdaq session tokens → the shared BMO/AMC vocabulary (verified live 2026-08-07).
_SESSION = {
    "time-pre-market": "BMO",
    "time-after-hours": "AMC",
    "time-not-supplied": None,
}


class NasdaqCalendarProvider(BaseProvider):
    name = "nasdaq"
    domain = "calendar"
    hosts = ("api.nasdaq.com",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0, headers={"User-Agent": UA})

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            rows = self.get_earnings_calendar(_today(), _today())
            ok = isinstance(rows, list)
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "bad payload", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def get_earnings_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        """Earnings rows in the shared normalized shape (symbol/date/estimates/session).

        One GET per calendar day in ``[start, end]``; `data` is sometimes null (guard
        before subscripting). Retries live in ProviderRegistry.call (#103/E-3).
        """
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        if end_d < start_d:
            return []
        items: list[dict[str, Any]] = []
        cursor = start_d
        while cursor <= end_d:
            items.extend(self._fetch_day(cursor.isoformat()))
            cursor += timedelta(days=1)
        return items

    def _fetch_day(self, day: str) -> list[dict[str, Any]]:
        resp = self._client.get(NASDAQ_EARNINGS, params={"date": day})
        if resp.status_code != 200:
            raise ProviderError.from_exception(
                httpx.HTTPStatusError(
                    f"Nasdaq earnings HTTP {resp.status_code}", request=resp.request, response=resp
                ),
                detail=f"Nasdaq earnings HTTP {resp.status_code}",
            )
        data = resp.json()
        rows = (data.get("data") or {}).get("rows") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            out.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "eps_estimate": _money(row.get("epsForecast")),
                    "eps_actual": None,
                    "revenue_estimate": None,
                    "revenue_actual": None,
                    "session": _SESSION.get(str(row.get("time", ""))),
                }
            )
        return out


def _money(value) -> float | None:
    """Parse Nasdaq's unit-suffixed strings ("$0.99", " ", "&nbsp;", "$—")."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip().replace("$", "").replace(",", "").replace("\xa0", "")
    if cleaned in {"", "-", "—", "&nbsp;"}:
        return None
    try:
        f = float(cleaned)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except ValueError:
        return None


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
