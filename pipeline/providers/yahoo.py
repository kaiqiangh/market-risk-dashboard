"""Quotes primary source: Yahoo Finance (yfinance, architecture §1.3).

Note: yfinance is free with no SLA (two 48h outages in 2025, review §3.1); it must go through
the degradation chain (Stooq fallback + last-good cache). This module only wraps the Provider;
it contains no business logic.
"""

from __future__ import annotations

import math
import time

import yfinance as yf

from pipeline.providers.base import (
    BaseProvider,
    HistoryResult,
    ProviderError,
    ProviderHealth,
    QuoteResult,
)
from pipeline.utils import now_utc

_PERIOD_MAP = {"1mo": "1mo", "1y": "1y", "3mo": "3mo", "6mo": "6mo", "2y": "2y", "5y": "5y"}


class YahooProvider(BaseProvider):
    name = "yfinance"
    priority = 1
    domain = "quotes"

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
        try:
            hist = yf.Ticker(symbol).history(period="1mo")
            if hist is None or len(hist) < 2:
                raise ProviderError(f"{symbol}: yfinance history is empty")
            closes = hist["Close"].dropna()
            if len(closes) < 2:
                raise ProviderError(f"{symbol}: not enough closing prices")
            price = float(closes.iloc[-1])
            change_1d = _pct(float(closes.iloc[-1]), float(closes.iloc[-2]))
            change_1w = _pct(float(closes.iloc[-1]), float(closes.iloc[-6])) if len(closes) >= 6 else None
            change_1m = _pct(float(closes.iloc[-1]), float(closes.iloc[0])) if len(closes) >= 2 else None
            volume = float(hist["Volume"].dropna().iloc[-1]) if "Volume" in hist and len(hist["Volume"].dropna()) else None
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
            raise ProviderError(f"{symbol}: yfinance quote failed: {exc}") from exc

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        if period not in _PERIOD_MAP:
            period = "1y"
        try:
            hist = yf.Ticker(symbol).history(period=_PERIOD_MAP[period], auto_adjust=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"{symbol}: yfinance history is empty")
            rows: list[dict] = []
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
            return HistoryResult(symbol=symbol, provider=self.name, rows=rows, period=period)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{symbol}: yfinance history failed: {exc}") from exc

    def get_history_range(self, symbol: str, start: str, end: str) -> HistoryResult:
        """Fetch history by date range (for calibration 2008/2018/2020 windows, architecture §1.8)."""
        try:
            hist = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=False)
            if hist is None or len(hist) == 0:
                raise ProviderError(f"{symbol}: yfinance range history is empty ({start}~{end})")
            rows: list[dict] = []
            for idx, row in hist.iterrows():
                date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
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
            return HistoryResult(symbol=symbol, provider=self.name, rows=rows, period=f"{start}~{end}")
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{symbol}: yfinance history_range failed: {exc}") from exc

    # Earnings calendar fallback (when the FMP primary source fails)
    def get_earnings_calendar(self, start: str, end: str) -> list[dict[str, str | None]]:
        """yfinance earnings calendar fallback: fetch earnings dates per US equity, filtered to the window."""
        items: list[dict[str, str | None]] = []
        errors: list[str] = []
        start_dt = _parse_date(start)
        end_dt = _parse_date(end)
        for symbol in _default_symbols(self.settings):
            try:
                cal = yf.Ticker(symbol).get_earnings_dates(limit=4)
                if cal is None or len(cal) == 0:
                    continue
                for idx in cal.index:
                    date = idx
                    if hasattr(idx, "date"):
                        date = idx.date()
                    date_str = date.isoformat() if hasattr(date, "isoformat") else str(date)
                    if start_dt and end_dt and start_dt <= str(date_str)[:10] <= end_dt:
                        items.append({"symbol": symbol, "date": str(date_str)[:10], "eps_estimate": None, "eps_actual": None, "revenue_estimate": None, "time": "AMC"})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{symbol}: {exc}")
                continue
        if not items and errors:
            raise ProviderError(f"yfinance calendar fallback failed: {'; '.join(errors[:3])}")
        return items


def _default_symbols(settings=None) -> list[str]:
    """US equity symbols for the earnings-calendar fallback, from the universe (D-8/#102).

    This used to be a hardcoded five-ticker list that had already drifted from
    config/universe.yaml; the universe is now the single home for the pool.
    """
    from pipeline.universe import AssetUniverse

    return AssetUniverse.load(settings).symbols("US")


def _parse_date(value: str) -> str | None:
    return value[:10] if value else None


class YahooCalendarProvider(YahooProvider):
    """Earnings calendar fallback Provider (registered to the calendar domain, architecture §1.3 fmp→yfinance)."""

    name = "yfinance_calendar"
    priority = 2
    domain = "calendar"


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
