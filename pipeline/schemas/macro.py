"""宏观数据集契约（架构 §3.2 指标映射 / 评审 §3.1 FRED 基石）。

payload 结构：按业务域分组的 MacroIndicator 列表 + FedWatch 快照。
T03 MacroCollector 负责填充；本模块只定义契约。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, FreshnessStatus, UTCDateTime

MacroUnit = Literal["pct", "bps", "index", "usd", "ratio", "level"]


class MacroIndicator(ContractModel):
    """单一宏观指标（原始数值存储，架构 §8.3）。"""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | None = None
    previous: float | None = None
    change_1m: float | None = None
    unit: MacroUnit = "level"
    source: str = Field(min_length=1)
    updated_at: UTCDateTime | None = None
    status: FreshnessStatus = "fresh"


class FedWatchRateProb(ContractModel):
    """某目标利率区间的概率（0-1）。"""

    target_rate: float
    probability: float = Field(ge=0.0, le=1.0)
    change_1d: float | None = None


class FedWatchSnapshot(ContractModel):
    """CME FedWatch 概率自算快照（架构 §1.6 冻结方法论）。"""

    meeting_date: UTCDateTime
    effective_rate: float
    implied_rate: float
    probabilities: list[FedWatchRateProb] = Field(default_factory=list)
    inferred_action: Literal["hold", "hike", "cut", "insufficient_data"] | None = None
    change_1d: dict[str, float] | None = None
    status: Literal["accumulating", "ready"] = "accumulating"
    # 免费结算历史仅约 5 个交易日（评审 P0-1）：较一周前变化在系统运行满 7 天前不可得，
    # 前端必须显示 insufficient data 状态而非 0/空值。


class MacroDataset(ContractModel):
    """宏观数据集 payload。"""

    rates: list[MacroIndicator] = Field(default_factory=list)
    credit: list[MacroIndicator] = Field(default_factory=list)
    inflation: list[MacroIndicator] = Field(default_factory=list)
    labor: list[MacroIndicator] = Field(default_factory=list)
    liquidity: list[MacroIndicator] = Field(default_factory=list)
    fx: list[MacroIndicator] = Field(default_factory=list)
    fedwatch: FedWatchSnapshot | None = None


class MacroEnvelope(BaseEnvelope):
    """macro.json 信封（payload 强类型）。"""

    payload: MacroDataset
