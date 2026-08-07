"""Quotes primary source: Yahoo Finance (yfinance, architecture §1.3).

Note: yfinance is free with no SLA (two 48h outages in 2025, review §3.1); it must go through
the degradation chain (Stooq fallback + last-good cache). This module only wraps the Provider;
it contains no business logic.
"""

from __future__ import annotations

import math
import time
from typing import Any

import yfinance as yf

from pipeline.providers.base import (
    BaseProvider,
    HistoryResult,
    ProviderError,
    ProviderHealth,
    QuoteResult,
)
from pipeline.utils import now_utc


def _to_rows(hist) -> list[dict[str, Any]]:
    """Normalize a yfinance DataFrame into the contract's OHLCV row shape (single copy, #103)."""
    rows: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        date = idx
        if hasattr(idx, "strftime"):
            date = idx.strftime("%Y-%m-%d")
        rows.append(
            {
                "date": str(date),
                "open": _clean(row.get("Open")),
                "high": _clean(row.get("High")),
                "low": _clean(row.get("Low")),
                "close": _clean(row.get("Close")),
                "volume": _clean(row.get("Volume")),
            }
        )
    return rows



_PERIOD_MAP = {"1mo": "1mo", "1y": "1y", "3mo": "3mo", "6mo": "6mo", "2y": "2y", "5y": "5y"}


class YahooProvider(BaseProvider):
    name = "yfinance"
    domain = "quotes"
    #: Host bucket keys for the #103 per-host rate limiter (tightest budget in config).
    hosts = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        # #103 (P-1): one 1y fetch per symbol — get_quote derives from the tail and
        # get_history("1y") reuses it (the old N+1 fetched 1mo then 1y).
        self._history_1y: dict[str, list[dict[str, Any]]] = {}

    def _fetch_1y(self, symbol: str) -> list[dict[str, Any]]:
        """Memoized 1y history — the single fetch per symbol that feeds quote + history."""
        if symbol in self._history_1y:
            return self._history_1y[symbol]
        try:
            hist = yf.Ticker(symbol).history(period="1y", auto_adjust=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"{symbol}: yfinance history is empty")
            rows = _to_rows(hist)
            self._history_1y[symbol] = rows
            return rows
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError.from_exception(exc, detail=f"{symbol}: yfinance history failed") from exc

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            # Lightweight probe: fetch SPY 1d history
            hist = yf.Ticker("SPY").history(period="5d")
            ok = hist is not None and len(hist) > 0
            return ProviderHealth(
                provider=self.name,
                ok=bool(ok),
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "empty history",
                checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name,
                ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200],
                checked_at=None,
            )

    def get_quote(self, symbol: str) -> QuoteResult:
        """Quote derived from the tail of the memoized 1y history (#103 P-1, no N+1)."""
        try:
            rows = self._fetch_1y(symbol)
            closes = [r["close"] for r in rows if r.get("close") is not None]
            if len(closes) < 2:
                raise ProviderError(f"{symbol}: not enough closing prices")
            price = closes[-1]
            change_1d = _pct(price, closes[-2])
            change_1w = _pct(price, closes[-6]) if len(closes) >= 6 else None
            change_1m = _pct(price, closes[-21]) if len(closes) >= 21 else _pct(price, closes[0])
            volume = rows[-1].get("volume") if rows else None
            return QuoteResult(
                symbol=symbol,
                price=price,
                change_1d=change_1d,
                change_1w=change_1w,
                change_1m=change_1m,
                volume=volume,
                source="yahoo",
                provider=self.name,
                updated_at=now_utc(),
                is_proxy=False,
            )
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError.from_exception(exc, detail=f"{symbol}: yfinance quote failed") from exc

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        if period not in _PERIOD_MAP:
            period = "1y"
        if period == "1y":
            # #103 (P-1): reuse the fetch get_quote already made — one 1y fetch per symbol.
            return HistoryResult(symbol=symbol, provider=self.name, rows=self._fetch_1y(symbol), period="1y")
        try:
            hist = yf.Ticker(symbol).history(period=_PERIOD_MAP[period], auto_adjust=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"{symbol}: yfinance history is empty")
            return HistoryResult(symbol=symbol, provider=self.name, rows=_to_rows(hist), period=period)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError.from_exception(exc, detail=f"{symbol}: yfinance history failed") from exc

    def get_history_range(self, symbol: str, start: str, end: str) -> HistoryResult:
        """Fetch history by date range (for calibration 2008/2018/2020 windows, architecture §1.8)."""
        try:
            hist = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"{symbol}: yfinance range history is empty ({start}~{end})")
            return HistoryResult(symbol=symbol, provider=self.name, rows=_to_rows(hist), period=f"{start}~{end}")
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{symbol}: yfinance history_range failed: {exc}") from exc


def _pct(latest: float, prev: float) -> float | None:
    if prev is None or math.isnan(prev) or prev == 0:
        return None
    return round((latest - prev) / prev * 100.0, 4)


def _clean(value) -> float | None:
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None
