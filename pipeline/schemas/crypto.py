"""加密资产数据集契约（架构 §3.2 cross_asset / 评审 §3 数据源矩阵 #7）。

T03 CoinGeckoCollector 负责填充；本模块只定义契约。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, UTCDateTime

CryptoSentiment = Literal["risk_on", "risk_off", "neutral"]


class CryptoAsset(ContractModel):
    symbol: str = Field(min_length=1, description="如 BTC / ETH / SOL")
    name: str = Field(min_length=1)
    price: float
    change_1d: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    source: str = Field(min_length=1)
    updated_at: UTCDateTime


class CryptoDataset(ContractModel):
    """crypto.json payload。"""

    assets: list[CryptoAsset] = Field(default_factory=list)
    btc_dominance: float | None = Field(default=None, ge=0.0, le=1.0)
    stablecoin_mcap: float | None = None
    market_cap_total: float | None = None
    sentiment: CryptoSentiment | None = None


class CryptoEnvelope(BaseEnvelope):
    payload: CryptoDataset
