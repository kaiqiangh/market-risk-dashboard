"""风险模型 6 维结构契约（架构 §3.2 冻结子集）。

- 风险分 0-100；比率 0-1；趋势三态；regime 9 状态。
- DriverContribution.evidence_ref 前向引用 factlayer.EvidenceRef；
  运行时解析在 pipeline/schemas/__init__.py 中通过 model_rebuild 完成。
  本模块不包含评分/判定业务逻辑（那是 T03 pipeline/risk/）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime

if TYPE_CHECKING:  # 仅类型检查期导入，避免运行时循环依赖
    from .factlayer import EvidenceRef

RiskDimensionKey = Literal[
    "macro", "liquidity_credit", "equity_structure", "volatility", "cross_asset", "trend"
]
RiskDirection = Literal["higher_is_riskier", "lower_is_riskier", "neutral"]
RiskLevel = Literal["risk_on", "low_risk", "caution", "high_risk", "severe_risk", "crisis"]
MarketRegime = Literal[
    "goldilocks", "risk_on", "disinflation", "reflation",
    "late_cycle", "stagflation", "liquidity_stress", "risk_off", "crisis",
]
RiskTrend = Literal["rising", "falling", "flat"]


class RiskIndicator(ContractModel):
    """子指标：原始值 + 5Y 百分位 + 映射后的风险分。"""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | None = None
    percentile: float | None = Field(default=None, ge=0.0, le=100.0, description="5Y 历史百分位 0-100")
    z_score: float | None = None
    risk_score: float = Field(ge=0.0, le=100.0, description="子指标映射后的风险分")
    direction: RiskDirection = "neutral"
    weight: float = Field(default=0.0, ge=0.0)
    source: str = Field(min_length=1)
    updated_at: UTCDateTime | None = None
    status: FreshnessStatus = "fresh"
    is_proxy: bool = Field(default=False, description="代理指标（资金流等）标注 Estimated/Proxy")


class RiskDimension(ContractModel):
    """风险维度（6 维之一）。"""

    key: RiskDimensionKey
    label: str = Field(min_length=1)
    weight: float = Field(ge=0.0, description="配置权重（config/risk_model.yaml）")
    effective_weight: float = Field(ge=0.0, description="重归一化后权重（缺失维度时重新分配）")
    score: float = Field(ge=0.0, le=100.0)
    indicators: list[RiskIndicator] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0, description="有数据指标占比")
    trend: RiskTrend = "flat"


class DriverContribution(ContractModel):
    """Top 驱动因素：对总分的贡献（权重 × 风险分）。"""

    dimension_key: RiskDimensionKey
    indicator_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    contribution: float
    change_1d: float | None = None
    evidence_ref: EvidenceRef | None = None


class RiskModelResult(ContractModel):
    """风险模型输出（risk.json payload 与 facts.json 内嵌）。"""

    model_version: str = Field(min_length=1)
    generated_at: UTCDateTime
    total_score: float = Field(ge=0.0, le=100.0)
    risk_level: RiskLevel
    trend_1d: float | None = None
    trend_1w: float | None = None
    trend_1m: float | None = None
    dimensions: list[RiskDimension] = Field(default_factory=list)
    top_drivers: list[DriverContribution] = Field(default_factory=list)
    regime: MarketRegime
    regime_evidence: list[str] = Field(default_factory=list, description="判定依据（可解释性）")
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    disclaimer: str = Field(
        default="本页风险分数为模型化的市场压力估计，并非精确的崩盘概率，不构成投资建议。"
    )


class RiskEnvelope(ContractModel):
    """risk.json 信封（payload 为 RiskModelResult，与事实层内嵌结构一致）。"""

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1)
    source: str | list[str]
    source_updated_at: UTCDateTime | None = None
    freshness_status: FreshnessStatus = "fresh"
    data_quality: float = Field(ge=0.0, le=1.0)
    payload: RiskModelResult
