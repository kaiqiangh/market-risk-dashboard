"""A-share memory pool source: AKShare via Tencent (architecture §1.3 frozen; pyproject.toml constraint).

Hard constraint: **akshare is only imported inside AkshareProvider** (isolating the impact of anti-scraping changes).
#97/#85: the Eastmoney history tier (ak.stock_zh_a_hist → push2his.eastmoney.com) is
geo-tiered and refuses this host (TLS completes, connection dropped, 0/~50 probes) — the
history endpoint now goes through the Tencent backend (stock_zh_a_hist_tx), which #85
verified answers from this host. Fallback chain: yfinance_a_share (p1, US-hosted) →
akshare-Tencent (p2, CN-hosted) → last-good cache.

Refresh cadence vs the CN session clock (#97): the scheduled full run lands before the
CN open (US morning), so A-share values serve the PREVIOUS CN close (15:00 CST = 07:00
UTC). A-share assets live inside equities.json (market=CN), whose freshness interval
reflects the run cadence — the CN-close vintage at that hour is expected, not a defect.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pipeline.providers.base import (
    BaseProvider,
    HistoryResult,
    ProviderError,
    ProviderHealth,
    QuoteResult,
)
from pipeline.utils import now_utc


def _to_ak_symbol(symbol: str) -> tuple[str, str]:
    """603986.SH → ("603986", "sh"); 301308.SZ → ("301308", "sz")."""
    base, suffix = symbol.split(".")
    return base, suffix.lower()


class AkshareProvider(BaseProvider):
    name = "akshare"
    domain = "a_share"
    # Tencent backend host (the per-(provider,host) limiter/breaker identity).
    hosts = ("web.ifzq.gtimg.cn",)

    def health(self) -> ProviderHealth:
        started = time.monotonic()
        try:
            import akshare  # noqa: F401  # constraint: import only here

            return ProviderHealth(
                provider=self.name, ok=True,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None, checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=f"akshare import failed: {exc}", checked_at=None,
            )

    def get_history(self, symbol: str, period: str = "1y") -> HistoryResult:
        base, market = _to_ak_symbol(symbol)

        def _fetch() -> Any:
            import akshare as ak  # constraint: import only here

            # #97/#85: Tencent backend (stock_zh_a_hist_tx) — the Eastmoney history tier
            # (stock_zh_a_hist) is geo-blocked from this host.
            df = ak.stock_zh_a_hist_tx(
                symbol=f"{market}{base}",
                start_date=_start_date(period),
                end_date=_today(),
                adjust="qfq",
            )
            if df is None or len(df) == 0:
                raise ProviderError(f"{symbol}: akshare history is empty")
            return df

        try:
            # #103/E-3: no nested retry (akshare failures are mostly persistent
            # ProxyError) — retries/classification live in ProviderRegistry.call.
            df = _fetch()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError.from_exception(exc, detail=f"{symbol}: akshare history failed") from exc

        rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "date": str(row.get("日期")),
                    "open": _f(row.get("开盘")),
                    "high": _f(row.get("最高")),
                    "low": _f(row.get("最低")),
                    "close": _f(row.get("收盘")),
                    "volume": _f(row.get("成交量")),
                }
            )
        return HistoryResult(symbol=symbol, provider=self.name, rows=rows, period=period)

    def get_quote(self, symbol: str) -> QuoteResult:
        hist = self.get_history(symbol, period="1mo")
        closes = [r["close"] for r in hist.rows if isinstance(r["close"], (int, float))]
        if len(closes) < 2:
            raise ProviderError(f"{symbol}: akshare not enough closes")
        return QuoteResult(
            symbol=symbol, price=float(closes[-1]),
            change_1d=_pct(float(closes[-1]), float(closes[-2])),
            change_1w=_pct(float(closes[-1]), float(closes[-6])) if len(closes) >= 6 else None,
            change_1m=_pct(float(closes[-1]), float(closes[0])) if len(closes) >= 2 else None,
            volume=hist.rows[-1].get("volume"),
            source="akshare", provider=self.name, updated_at=now_utc(), is_proxy=False,
        )


def _f(value) -> float | None:
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _pct(latest: float, prev: float) -> float | None:
    if prev is None or prev == 0:
        return None
    return round((latest - prev) / prev * 100.0, 4)


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _start_date(period: str) -> str:
    from datetime import datetime, timedelta, timezone

    days = {"1mo": 45, "3mo": 100, "6mo": 200, "1y": 400, "2y": 750, "5y": 1850}.get(period, 400)
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%d")
