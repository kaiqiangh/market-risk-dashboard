"""Equities dataset contract (architecture §8.10/§8.11: 5 US equities + 10 A-share card-level indicators).

Filled by the T03 MarketCollector; this module only defines the contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

Market = Literal["US", "CN", "KR", "HK"]


class EquityAsset(ContractModel):
    """Card-level data of a single equity."""

    symbol: str = Field(min_length=1, description="asset code in uppercase, e.g. NVDA / 603986.SH")
    name: str = Field(min_length=1)
    name_zh: str | None = None
    market: Market = "US"
    sector: str = "other"
    theme: list[str] = Field(default_factory=list)
    price: float
    currency: str = "USD"
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    change_ytd: float | None = None
    volume: float | None = None
    market_cap: float | None = None
    ma50_distance_pct: float | None = None
    ma200_distance_pct: float | None = None
    rsi14: float | None = Field(default=None, ge=0.0, le=100.0)
    percentile_1y: float | None = Field(default=None, ge=0.0, le=100.0, description="percentile within the ~1y history window (#70)")
    percentile_1y_obs: int = Field(default=0, ge=0, description="observations behind the percentile (#70)")
    source: str = Field(min_length=1)
    updated_at: UTCDateTime
    is_proxy: bool = False


class EquitiesDataset(ContractModel):
    """equities.json payload."""

    assets: list[EquityAsset] = Field(default_factory=list)


class EquitiesEnvelope(BaseEnvelope):
    payload: EquitiesDataset
