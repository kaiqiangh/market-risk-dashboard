"""首页聚合 dashboard.json 契约（架构 §2 文件列表 L299 + §3.6）。

与前端 src/schemas/dashboard.ts（Zod）同构：
- payload 聚合 risk/regime/top_drivers/cross_asset/catalysts/sector_performance 关键字段。
- 管道在 --full 流程产出；前端 Overview 页可单文件消费（T05 起）。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel
from .risk import DriverContribution, MarketRegime, RiskModelResult


class DashboardAsset(ContractModel):
    """跨资产确认信号条目（equity/crypto 等）。"""

    asset: str = Field(min_length=1)
    category: str = Field(min_length=1)
    change_1d: float | None = None


class DashboardPayload(ContractModel):
    """dashboard.json payload（与前端 Zod strict 结构一致）。"""

    risk: RiskModelResult
    regime: MarketRegime
    top_drivers: list[DriverContribution] = Field(default_factory=list)
    cross_asset: list[DashboardAsset] = Field(default_factory=list)
    catalysts: list[dict[str, Any]] = Field(default_factory=list)
    sector_performance: list[dict[str, Any]] = Field(default_factory=list)


class DashboardEnvelope(BaseEnvelope):
    """dashboard.json 信封（payload 强类型）。"""

    payload: DashboardPayload
