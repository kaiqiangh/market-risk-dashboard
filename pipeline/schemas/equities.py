"""股票数据集契约（架构 §8.10/§8.11：美股 5 只 + A 股 10 只卡片级指标）。

T03 MarketCollector 负责填充；本模块只定义契约。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

Market = Literal["US", "CN", "KR", "HK"]


class EquityAsset(ContractModel):
    """单只股票卡片级数据。"""

    symbol: str = Field(min_length=1, description="资产代码统一大写，如 NVDA / 603986.SH")
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
    percentile_5y: float | None = Field(default=None, ge=0.0, le=100.0)
    source: str = Field(min_length=1)
    updated_at: UTCDateTime
    is_proxy: bool = False


class EquitiesDataset(ContractModel):
    """equities.json payload。"""

    assets: list[EquityAsset] = Field(default_factory=list)


class EquitiesEnvelope(BaseEnvelope):
    payload: EquitiesDataset
