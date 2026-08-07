"""Macro primary source: FRED API (architecture §1.3 absolute cornerstone; review §3.1).

Direct httpx connection with retry/rate limiting; API key comes from the local .env (DATA_FRED_API_KEY).
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

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# FRED series used by the MVP (architecture §3.2 indicator mapping + calibration §1.8)
SERIES_CATALOG: dict[str, dict[str, str]] = {
    "DGS10": {"label": "10-Year Treasury Yield", "unit": "pct"},
    "DGS2": {"label": "2-Year Treasury Yield", "unit": "pct"},
    "DFII10": {"label": "10-Year Real Yield", "unit": "pct"},
    "T10YIE": {"label": "10Y Breakeven Inflation", "unit": "pct"},
    "DFF": {"label": "Effective Federal Funds Rate", "unit": "pct"},
    "EFFR": {"label": "Effective Federal Funds Rate", "unit": "pct"},
    "VIXCLS": {"label": "CBOE Volatility Index (VIX)", "unit": "index"},
    "BAMLH0A0HYM2": {"label": "ICE BofA US High Yield OAS", "unit": "pct"},
    "BAMLC0A0CM": {"label": "ICE BofA US Corporate OAS", "unit": "pct"},
    "WALCL": {"label": "Fed Total Assets", "unit": "usd"},
    "RRPONTSYD": {"label": "Overnight Reverse Repo", "unit": "usd"},
    "WTREGEN": {"label": "Treasury General Account", "unit": "usd"},
    "WRESBAL": {"label": "Bank Reserves", "unit": "usd"},
    "CPIAUCSL": {"label": "CPI All Urban Consumers", "unit": "index"},
    "PCEPI": {"label": "PCE Price Index", "unit": "index"},
    "UNRATE": {"label": "Unemployment Rate", "unit": "pct"},
    "PAYEMS": {"label": "Nonfarm Payrolls", "unit": "level"},
    "NAPM": {"label": "ISM Manufacturing PMI (proxy)", "unit": "index"},
    "M2SL": {"label": "M2 Money Stock", "unit": "usd"},
    "DTWEXBGS": {"label": "Nominal Broad Dollar Index", "unit": "index"},
    "MOVE": {"label": "Merrill Option Volatility Estimate", "unit": "index"},
    "GOLDPMGBD228NLBM": {"label": "Gold Fixing Price", "unit": "usd"},
    "DCOILWTICO": {"label": "WTI Crude Oil", "unit": "usd"},
}


class FredProvider(BaseProvider):
    name = "fred"
    domain = "macro"
    hosts = ("api.stlouisfed.org",)

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fred_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0)

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_FRED_API_KEY", checked_at=None)
        started = time.monotonic()
        try:
            obs = self.get_series("VIXCLS", limit=1)
            ok = len(obs) > 0
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "empty series", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def get_series(self, series_id: str, start: str | None = None, end: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ProviderError("FRED: missing DATA_FRED_API_KEY (local .env)")
        if series_id not in SERIES_CATALOG and series_id not in ("DFF",):
            # Allow any known series; unknown series are still fetched (FRED will return empty)
            pass

        def _fetch() -> dict[str, Any]:
            params: dict[str, Any] = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "asc",
            }
            if start:
                params["observation_start"] = start
            if end:
                params["observation_end"] = end
            if limit:
                params["limit"] = limit
                params["sort_order"] = "desc"
            resp = self._client.get(FRED_BASE, params=params)
            if resp.status_code != 200:
                # #103/E-3: classification + redaction at the one boundary (no nested retry).
                raise ProviderError.from_exception(
                    httpx.HTTPStatusError(
                        f"FRED {series_id} HTTP {resp.status_code}", request=resp.request, response=resp
                    ),
                    detail=f"FRED {series_id}: HTTP {resp.status_code}",
                )
            return resp.json()

        # #103/E-3: retries live in ProviderRegistry.call, not here.
        data = _fetch()

        observations = data.get("observations", [])
        rows: list[dict[str, Any]] = []
        for obs in observations:
            value = obs.get("value")
            if value in (".", "", None):
                continue
            try:
                fv = float(value)
                if math.isnan(fv) or math.isinf(fv):
                    continue
                rows.append({"date": obs["date"], "value": fv})
            except (TypeError, ValueError):
                continue
        if limit:
            rows = rows[::-1]
        return rows
