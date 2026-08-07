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

# FRED series catalog (#96, uses #84): every entry is the 27-series roster (plus EFFR for
# the FedWatch anchor) with the metadata the collector and the history manifest need —
# `frequency` (frequency-aware change/status lookbacks), `units` (server-side transform,
# #84 §1: CPI/PCE are indexes at ~330, published as YoY percent; PAYEMS is a level,
# published as the monthly change), `scale` (WALCL is Mil-$ vs RRPONTSYD Bil-$ — the
# same `usd` unit at different magnitudes). Dead IDs (NAPM/MOVE/GOLDPMGBD228NLBM) that
# FRED rejects with HTTP 400 are gone.
SERIES_CATALOG: dict[str, dict[str, str]] = {
    # rates
    "DGS10": {"label": "10-Year Treasury Yield", "unit": "pct", "frequency": "daily", "scale": "pct"},
    "DGS2": {"label": "2-Year Treasury Yield", "unit": "pct", "frequency": "daily", "scale": "pct"},
    "DFII10": {"label": "10-Year Real Yield", "unit": "pct", "frequency": "daily", "scale": "pct"},
    "DFF": {"label": "Effective Federal Funds Rate", "unit": "pct", "frequency": "daily", "scale": "pct"},
    # credit
    "BAMLH0A0HYM2": {"label": "ICE BofA US High Yield OAS", "unit": "pct", "frequency": "daily", "scale": "pct"},
    "BAMLC0A0CM": {"label": "ICE BofA US Corporate OAS", "unit": "pct", "frequency": "daily", "scale": "pct"},
    # volatility (#84 §5: VIX belongs in its own group, not under rates)
    "VIXCLS": {"label": "CBOE Volatility Index (VIX)", "unit": "index", "frequency": "daily", "scale": "index"},
    # inflation (#84 §1: indexes published as YoY percent via units=pc1; T10YIE moves here)
    "CPIAUCSL": {"label": "CPI All Urban Consumers (YoY)", "unit": "pct", "frequency": "monthly", "scale": "pct", "units": "pc1"},
    "CPILFESL": {"label": "Core CPI (YoY)", "unit": "pct", "frequency": "monthly", "scale": "pct", "units": "pc1"},
    "PCEPILFE": {"label": "Core PCE (YoY)", "unit": "pct", "frequency": "monthly", "scale": "pct", "units": "pc1"},
    "T5YIFR": {"label": "5Y5Y Forward Inflation Expectation", "unit": "pct", "frequency": "daily", "scale": "pct"},
    "T10YIE": {"label": "10Y Breakeven Inflation", "unit": "pct", "frequency": "daily", "scale": "pct"},
    # labor (#84 §1: PAYEMS is total employed — published as the monthly change via units=chg)
    "PAYEMS": {"label": "Nonfarm Payrolls (MoM change)", "unit": "level", "frequency": "monthly", "scale": "k", "units": "chg"},
    "UNRATE": {"label": "Unemployment Rate", "unit": "pct", "frequency": "monthly", "scale": "pct"},
    "ICSA": {"label": "Initial Jobless Claims", "unit": "level", "frequency": "weekly", "scale": "k"},
    "CCSA": {"label": "Continued Claims", "unit": "level", "frequency": "weekly", "scale": "k"},
    "CIVPART": {"label": "Labor Force Participation Rate", "unit": "pct", "frequency": "monthly", "scale": "pct"},
    # liquidity (#84 §1: WALCL/WRESBAL/WTREGEN are Mil-$, RRPONTSYD is Bil-$)
    "WALCL": {"label": "Fed Total Assets", "unit": "usd", "frequency": "weekly", "scale": "mil_usd"},
    "WRESBAL": {"label": "Bank Reserves", "unit": "usd", "frequency": "weekly", "scale": "mil_usd"},
    "WTREGEN": {"label": "Treasury General Account", "unit": "usd", "frequency": "weekly", "scale": "mil_usd"},
    "RRPONTSYD": {"label": "Overnight Reverse Repo", "unit": "usd", "frequency": "daily", "scale": "bil_usd"},
    "SOFR": {"label": "Secured Overnight Financing Rate", "unit": "pct", "frequency": "daily", "scale": "pct"},
    # fx (#84 §1: DTWEX* lag 3-7 calendar days routinely — see freshness note)
    "DTWEXBGS": {"label": "Nominal Broad Dollar Index", "unit": "index", "frequency": "daily", "scale": "index"},
    "DTWEXAFEGS": {"label": "Dollar Index (Advanced FE)", "unit": "index", "frequency": "daily", "scale": "index"},
    "DEXUSEU": {"label": "USD per EUR", "unit": "level", "frequency": "daily", "scale": "level"},
    "DEXJPUS": {"label": "JPY per USD", "unit": "level", "frequency": "daily", "scale": "level"},
    "DEXCHUS": {"label": "CNY per USD", "unit": "level", "frequency": "daily", "scale": "level"},
    # FedWatch anchor (not a published card)
    "EFFR": {"label": "Effective Federal Funds Rate", "unit": "pct", "frequency": "daily", "scale": "pct"},
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

    def get_series(self, series_id: str, start: str | None = None, end: str | None = None,
                   limit: int | None = None, units: str = "lin") -> list[dict[str, Any]]:
        if not self.api_key:
            raise ProviderError("FRED: missing DATA_FRED_API_KEY (local .env)")

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
            # #84 §1: server-side transform (lin/chg/ch1/pch/pc1/pca/cch/cca/log) — CPI/PCE
            # are indexes published as YoY percent; PAYEMS is a level published as the
            # monthly change. No extra request, no hand-rolled YoY maths.
            if units != "lin":
                params["units"] = units
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
