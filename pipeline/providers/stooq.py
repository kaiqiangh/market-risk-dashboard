"""Quotes fallback source: Stooq EOD CSV (architecture §1.3/review §3.1).

Free, no key required; EOD data only. Direct httpx connection (browser UA to avoid anti-scraping).
"""

from __future__ import annotations

import io
import math
import time

import httpx

from pipeline.providers.base import (
    BaseProvider,
    HistoryResult,
    ProviderError,
    ProviderHealth,
    QuoteResult,
)
from pipeline.utils import now_utc

STOOQ_URL = "https://stooq.com/q/d/l/"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _stooq_symbol(symbol: str) -> str:
    """US stock → stooq code (aapl.us); indices/futures not applicable returned lowercased as-is."""
    base = symbol.replace("^", "").lower()
    if "." not in base and not base.startswith(("gc", "si", "hg", "cl")):
        return f"{base}.us"
    return base


class StooqProvider(BaseProvider):
    name = "stooq"
    domain = "quotes"
    hosts = ("stooq.com",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=10.0, headers={"User-Agent": UA})

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            resp = self._client.get(STOOQ_URL, params={"s": "spy.us", "i": "d"})
            ok = resp.status_code == 200 and resp.text.strip().startswith("Date")
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else f"HTTP {resp.status_code}", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def _fetch_csv(self, symbol: str) -> list[dict[str, float | str]]:
        resp = self._client.get(STOOQ_URL, params={"s": _stooq_symbol(symbol), "i": "d"})
        if resp.status_code != 200:
            raise ProviderError(f"{symbol}: stooq HTTP {resp.status_code}")
        text = resp.text.strip()
        if not text or not text.startswith("Date"):
            raise ProviderError(f"{symbol}: stooq no data")
        rows: list[dict[str, float | str]] = []
        for line in text.splitlines()[1:]:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                rows.append(
                    {
                        "date": parts[0],
                        "open": _f(parts[1]),
                        "high": _f(parts[2]),
                        "low": _f(parts[3]),
                        "close": _f(parts[4]),
                        "volume": _f(parts[5]),
                    }
                )
            except (ValueError, IndexError):
                continue
        if not rows:
            raise ProviderError(f"{symbol}: stooq parse empty")
        return rows

    def get_quote(self, symbol: str) -> QuoteResult:
        rows = self._fetch_csv(symbol)
        closes = [r["close"] for r in rows if isinstance(r["close"], (int, float))]
        if len(closes) < 2:
            raise ProviderError(f"{symbol}: stooq not enough closes")
        price = float(closes[-1])
        return QuoteResult(
            symbol=symbol, price=price,
            change_1d=_pct(float(closes[-1]), float(closes[-2])),
            change_1w=_pct(float(closes[-1]), float(closes[-6])) if len(closes) >= 6 else None,
            change_1m=_pct(float(closes[-1]), float(closes[0])) if len(closes) >= 2 else None,
            volume=rows[-1].get("volume") if isinstance(rows[-1].get("volume"), (int, float)) else None,
            source="stooq", provider=self.name,
            updated_at=now_utc(), is_proxy=True,
        )

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        rows = self._fetch_csv(symbol)
        return HistoryResult(symbol=symbol, provider=self.name, rows=rows, period=period)


def _f(value: str) -> float | None:
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _pct(latest: float, prev: float) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((latest - prev) / prev * 100.0, 4)
