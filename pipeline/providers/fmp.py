"""Earnings calendar primary source: Financial Modeling Prep free tier (architecture §1.3 frozen).

Since #83 the free tier lives on the ``/stable`` namespace — ``/api/v3/*`` returns 403
"Legacy Endpoint" for every path, including ``earning_calendar``. The stable payload also
renamed the fields (``eps`` → ``epsActual``) and **dropped ``time``**, so the BMO/AMC
session signal is gone here; the Nasdaq fallback restores it. 250 req/day free quota is
enough for one range call per day; on failure degrades to the Nasdaq fallback (#94).
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
)

# #83: the whole /api/v3 namespace is retired — FMP_BASE moved to /stable and the
# earnings endpoint renamed (earning_calendar → earnings-calendar). Both verified live.
FMP_BASE = "https://financialmodelingprep.com/stable"
EARNINGS_ENDPOINT = f"{FMP_BASE}/earnings-calendar"


class FmpProvider(BaseProvider):
    name = "fmp"
    domain = "calendar"
    hosts = ("financialmodelingprep.com",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fmp_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0)

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
        """Earnings rows in the shared normalized shape (symbol/date/estimates/session).

        ``session`` is always None here — the stable payload dropped ``time`` (#83); the
        Nasdaq fallback supplies BMO/AMC. Retries live in ProviderRegistry.call (#103/E-3).
        """
        if not self.api_key:
            raise ProviderError("FMP: missing DATA_FMP_API_KEY (local .env)")

        resp = self._client.get(
            EARNINGS_ENDPOINT,
            params={"from": start, "to": end, "apikey": self.api_key},
        )
        if resp.status_code != 200:
            raise ProviderError.from_exception(
                httpx.HTTPStatusError(
                    f"FMP calendar HTTP {resp.status_code}", request=resp.request, response=resp
                ),
                detail=f"FMP calendar HTTP {resp.status_code}",
            )
        data = resp.json()
        if not isinstance(data, list):
            raise ProviderError("FMP calendar unexpected payload")

        items: list[dict[str, Any]] = []
        for row in data:
            symbol = str(row.get("symbol", "")).upper()
            date = str(row.get("date", ""))
            if not symbol or not date:
                continue
            items.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "eps_estimate": _f(row.get("epsEstimated")),
                    # stable renamed `eps` → `epsActual` (#83) — reading the old key would
                    # silently produce eps_actual=None forever.
                    "eps_actual": _f(row.get("epsActual")),
                    "revenue_estimate": _f(row.get("revenueEstimated")),
                    "revenue_actual": _f(row.get("revenueActual")),
                    "session": None,
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
