"""财报日历主源：Financial Modeling Prep 免费层（架构 §1.3 冻结）。

250 req/day 免费额度，够 ~40 标的每日一次；失败降级到 yfinance 兜底。
"""

from __future__ import annotations

import math
import time
from typing import Any

import httpx

from pipeline.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderHealth,
    retry_with_backoff,
)

FMP_BASE = "https://financialmodelingprep.com/api/v3"


class FmpProvider(BaseProvider):
    name = "fmp"
    priority = 1
    domain = "calendar"

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fmp_api_key
        self._client = httpx.Client(timeout=15.0)

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_FMP_API_KEY", checked_at=None)
        started = time.monotonic()
        try:
            events = self.get_earnings_calendar(_today(), _today())
            ok = isinstance(events, list)
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
        if not self.api_key:
            raise ProviderError("FMP: 缺少 DATA_FMP_API_KEY（本机 .env）")

        def _fetch() -> dict[str, Any]:
            resp = self._client.get(
                f"{FMP_BASE}/earning_calendar",
                params={"from": start, "to": end, "apikey": self.api_key},
            )
            if resp.status_code != 200:
                raise ProviderError(f"FMP calendar HTTP {resp.status_code}")
            data = resp.json()
            if not isinstance(data, list):
                raise ProviderError("FMP calendar unexpected payload")
            return {"items": data}

        try:
            result = retry_with_backoff(_fetch, max_retries=2, backoff_base=1.0, jitter=True)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"FMP calendar: {exc}") from exc

        items: list[dict[str, Any]] = []
        for row in result["items"]:
            symbol = str(row.get("symbol", "")).upper()
            date = str(row.get("date", ""))
            if not symbol or not date:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "eps_estimate": _f(row.get("epsEstimated")),
                    "eps_actual": _f(row.get("eps")),
                    "revenue_estimate": _f(row.get("revenueEstimated")),
                    "time": row.get("time") or "AMC",
                }
            )
        return items


def _f(value) -> float | None:
    try:
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    except (TypeError, ValueError):
        return None


def _today() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
