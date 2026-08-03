"""Homepage aggregation dashboard.json contract (architecture §2 file list L299 + §3.6).

Isomorphic to the frontend src/schemas/dashboard.ts (Zod):
- payload aggregates key fields from risk/regime/top_drivers/cross_asset/catalysts/sector_performance.
- produced by the pipeline in the --full flow; the frontend Overview page can consume a single file (since T05).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel
from .risk import DriverContribution, MarketRegime, RiskModelResult


class DashboardAsset(ContractModel):
    """Cross-asset confirmation signal entry (equity/crypto etc.)."""

    asset: str = Field(min_length=1)
    category: str = Field(min_length=1)
    change_1d: float | None = None


class DashboardPayload(ContractModel):
    """dashboard.json payload (consistent with the frontend Zod strict structure)."""

    risk: RiskModelResult
    regime: MarketRegime
    top_drivers: list[DriverContribution] = Field(default_factory=list)
    cross_asset: list[DashboardAsset] = Field(default_factory=list)
    catalysts: list[dict[str, Any]] = Field(default_factory=list)
    sector_performance: list[dict[str, Any]] = Field(default_factory=list)


class DashboardEnvelope(BaseEnvelope):
    """dashboard.json envelope (strongly typed payload)."""

    payload: DashboardPayload
