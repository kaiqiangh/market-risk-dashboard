"""Risk model 6-dimension structure contract (architecture §3.2 frozen subset).

- Risk scores 0-100; ratios 0-1; three-state trend; 9-state regime.
- DriverContribution.evidence_ref forward-references factlayer.EvidenceRef;
  runtime resolution happens in pipeline/schemas/__init__.py via model_rebuild.
  This module contains no scoring/decision business logic (that is T03 pipeline/risk/).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime

if TYPE_CHECKING:  # import only for type checking to avoid a runtime circular dependency
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
    """Sub-indicator: raw value + 5Y percentile + mapped risk score."""

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: float | None = None
    percentile: float | None = Field(default=None, ge=0.0, le=100.0, description="5Y historical percentile 0-100")
    z_score: float | None = None
    risk_score: float = Field(ge=0.0, le=100.0, description="mapped sub-indicator risk score")
    direction: RiskDirection = "neutral"
    weight: float = Field(default=0.0, ge=0.0)
    source: str = Field(min_length=1)
    updated_at: UTCDateTime | None = None
    status: FreshnessStatus = "fresh"
    is_proxy: bool = Field(default=False, description="proxy indicator (e.g. fund flow) marked Estimated/Proxy")


class RiskDimension(ContractModel):
    """Risk dimension (one of the 6)."""

    key: RiskDimensionKey
    label: str = Field(min_length=1)
    weight: float = Field(ge=0.0, description="configured weight (config/risk_model.yaml)")
    effective_weight: float = Field(ge=0.0, description="weight after renormalization (redistributed when dimensions are missing)")
    score: float = Field(ge=0.0, le=100.0)
    indicators: list[RiskIndicator] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0, description="share of indicators with data")
    trend: RiskTrend = "flat"


class DriverContribution(ContractModel):
    """Top driver: contribution to the total score (weight × risk score)."""

    dimension_key: RiskDimensionKey
    indicator_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    contribution: float
    change_1d: float | None = None
    evidence_ref: EvidenceRef | None = None


class RiskModelResult(ContractModel):
    """Risk model output (risk.json payload, also embedded in facts.json)."""

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
    regime_evidence: list[str] = Field(default_factory=list, description="decision basis (explainability)")
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    disclaimer: str = Field(
        default="This indicator is a modeled estimate of market stress based on historical data and current market signals. It is not a definitive probability or investment advice."
    )


class RiskEnvelope(ContractModel):
    """risk.json envelope (payload is RiskModelResult, consistent with the embedded fact layer structure)."""

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1)
    source: str | list[str]
    source_updated_at: UTCDateTime | None = None
    freshness_status: FreshnessStatus = "fresh"
    data_quality: float = Field(ge=0.0, le=1.0)
    payload: RiskModelResult
