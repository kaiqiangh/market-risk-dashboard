"""Commodities dataset contract (PRD §7 metals/oil; architecture §3.2 cross_asset).

Filled by the T03 MarketCollector (quotes domain); this module only defines the contract.
Covers the universe.yaml `metals` (GC=F gold, SI=F silver, HG=F copper) and `oil` (CL=F WTI)
groups. Commodity cards show price + 1d/1w/1m changes — no technicals, unlike equities.
"""

from __future__ import annotations

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime


class CommodityAsset(ContractModel):
    symbol: str = Field(min_length=1, description="futures ticker, e.g. GC=F / SI=F / HG=F / CL=F")
    name: str = Field(min_length=1)
    name_zh: str | None = None
    price: float
    currency: str = "USD"
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    source: str = Field(min_length=1)
    updated_at: UTCDateTime


class CommoditiesDataset(ContractModel):
    """commodities.json payload."""

    assets: list[CommodityAsset] = Field(default_factory=list)


class CommoditiesEnvelope(BaseEnvelope):
    payload: CommoditiesDataset
