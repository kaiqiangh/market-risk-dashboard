"""A-share memory pool primary source: AKShare (architecture §1.3 frozen; pyproject.toml constraint).

Hard constraint: **akshare is only imported inside AkshareProvider** (isolating the impact of anti-scraping changes).
AKShare depends on Eastmoney/Sina public interfaces that may be blocked by anti-scraping/proxies → use the
degradation chain + last-good.
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
    retry_with_backoff,
)
from pipeline.utils import now_utc


def _to_ak_symbol(symbol: str) -> tuple[str, str]:
    """603986.SH → ("603986", "sh"); 301308.SZ → ("301308", "sz")."""
    base, suffix = symbol.split(".")
    return base, suffix.lower()


class AkshareProvider(BaseProvider):
    name = "akshare"
    domain = "a_share"

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

            df = ak.stock_zh_a_hist(
                symbol=base,
                period="daily",
                start_date=_start_date(period),
                end_date=_today(),
                adjust="qfq",
            )
            if df is None or len(df) == 0:
                raise ProviderError(f"{symbol}: akshare history is empty")
            return df

        try:
            # akshare failures are mostly persistent network/anti-scraping issues (ProxyError);
            # retrying is pointless → no retry, fast degrade
            df = retry_with_backoff(_fetch, max_retries=0, backoff_base=0.0, jitter=False)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"{symbol}: akshare history failed: {exc}") from exc

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
