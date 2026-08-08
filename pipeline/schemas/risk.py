"""Risk model 6-dimension structure contract (architecture §3.2 frozen subset).

- Risk scores 0-100; ratios 0-1; three-state trend; 9-state regime.
- DriverContribution.evidence_ref forward-references factlayer.EvidenceRef;
  runtime resolution happens in pipeline/schemas/__init__.py via model_rebuild.
  This module contains no scoring/decision business logic (that is T03 pipeline/risk/).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import Field

from .envelope import BaseEnvelope, ContractModel, FreshnessStatus, UTCDateTime

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
    "indeterminate",
]
RiskTrend = Literal["rising", "falling", "flat"]
RiskEvidenceState = Literal["complete", "partial", "insufficient_evidence"]
RiskCalibrationStatus = Literal["provisional", "calibrated"]


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
    # No default (#69/#101): an omitted disclosure would read as "not a proxy", which is the
    # silent under-claim #69 exists to prevent. Every producer already states it explicitly.
    is_proxy: bool = Field(description="proxy indicator (e.g. fund flow) marked Estimated/Proxy")


class RiskDimension(ContractModel):
    """Risk dimension (one of the 6)."""

    key: RiskDimensionKey
    label: str = Field(min_length=1)
    weight: float = Field(ge=0.0, description="configured weight (config/risk_model.yaml)")
    effective_weight: float = Field(ge=0.0, description="weight after renormalization (redistributed when dimensions are missing)")
    score: float = Field(ge=0.0, le=100.0)
    indicators: list[RiskIndicator] = Field(default_factory=list)
    coverage: float = Field(ge=0.0, le=1.0, description="share of indicators with data (proxy-backed indicators discounted, #69)")
    trend: RiskTrend = "flat"
    evidence_state: RiskEvidenceState | None = None
    missing_indicators: list[str] = Field(default_factory=list)


class BreadthSnapshot(ContractModel):
    """Breadth sample disclosure (#69): the ratio plus the qualifying/considered counts.

    A thinning sample (4 of 18 constituents vs 18 of 18) is visible in the published
    data, not hidden behind a confidently-stated ratio.
    """

    breadth_above_ma200: float | None = Field(default=None, ge=0.0, le=1.0)
    breadth_qualifying: int = Field(default=0, ge=0, description="series closing above their 200-day MA")
    breadth_considered: int = Field(default=0, ge=0, description="series long enough to qualify")
    new_highs_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    new_lows_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    new_highs_qualifying: int = Field(default=0, ge=0)
    new_lows_qualifying: int = Field(default=0, ge=0)
    new_considered: int = Field(default=0, ge=0, description="series considered for new highs/lows")
    small_cap_relative: float | None = None
    semis_relative: float | None = None
    # Keeps its default, unlike the other two is_proxy fields (#101). This one is built by
    # model_validate() from the untyped ctx["breadth"] bag, and the default leans the
    # self-incriminating way: an omission over-claims proxy-ness. #69 guards against the
    # opposite error — a proxy quietly presenting itself as a measurement.
    is_proxy: bool = Field(default=True, description="MVP breadth uses index proxies (SPY/IWM/SOXX)")
    note: str = Field(default="", min_length=0)


class DriverContribution(ContractModel):
    """Top driver: contribution to the total score (weight × risk score)."""

    dimension_key: RiskDimensionKey
    indicator_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    contribution: float
    change_1d: float | None = None
    evidence_ref: EvidenceRef | None = None
    is_proxy: bool = Field(description="proxy/estimated indicator, discounted in coverage (#69)")
    discount: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="combined trust discount applied (1.0 none; proxy discount; proxy × degrade factor)",
    )


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
    # Required key, nullable value (#69/#101): "we had no breadth sample" must be written down
    # as `null`, not left out. A missing key is indistinguishable from a forgotten one.
    breadth: BreadthSnapshot | None = Field(description="breadth sample disclosure (#69)")
    regime: MarketRegime
    regime_evidence: list[str] = Field(default_factory=list, description="decision basis (explainability)")
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_factors: dict[str, float] = Field(default_factory=dict)
    disclaimer: str = Field(
        default="This indicator is a modeled estimate of market stress based on historical data and current market signals. Data trust is not statistical confidence, a calibrated probability, or investment advice."
    )
    evidence_state: RiskEvidenceState | None = None
    evidence_coverage: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="effective weighted evidence coverage, including proxy discounts",
    )
    score_lower_bound: float | None = Field(default=None, ge=0.0, le=100.0)
    score_upper_bound: float | None = Field(default=None, ge=0.0, le=100.0)
    calibration_policy_version: str = Field(default="1.0.0", min_length=1)
    calibration_status: RiskCalibrationStatus = "provisional"


class RiskEnvelope(BaseEnvelope):
    """risk.json envelope (payload is RiskModelResult, consistent with the embedded fact layer structure).

    Inherits the base envelope shape (#64): freshness_status is required with no default, so
    the risk card cannot certify itself as fresh — the only producer is finalize_freshness.
    """

    payload: RiskModelResult
