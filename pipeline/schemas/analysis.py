"""AI analysis output contract (architecture §3.4; automation produces analysis.zh-CN.json / analysis.en.json).

- Files are self-describing contracts (carry schema_version/generated_at/language), not wrapped in BaseEnvelope.
- Bilingual consistency (architecture §1.5/§3.4): market_state/market_regime/confidence/evidence_refs
  and all numbers must match exactly between zh-CN and en; only the prose language may differ.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime
from .factlayer import EvidenceRef

AnalysisLanguage = Literal["zh-CN", "en"]


class SignalClaim(ContractModel):
    """A claim with evidence."""

    claim: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class CaseStatement(ContractModel):
    """A scenario (bull/base/bear) statement."""

    title: str = Field(min_length=1)
    points: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class AnalysisDataset(ContractModel):
    """AI bilingual briefing (single-language file)."""

    schema_version: str = Field(min_length=1)
    generated_at: UTCDateTime
    language: AnalysisLanguage
    market_state: str = Field(min_length=1, description="consistent with the risk level (risk_level)")
    market_regime: str = Field(min_length=1, description="consistent with the fact layer regime")
    summary: str = Field(min_length=1)
    top_risk_drivers: list[SignalClaim] = Field(default_factory=list)
    supporting_signals: list[SignalClaim] = Field(default_factory=list)
    contradicting_signals: list[SignalClaim] = Field(default_factory=list)
    what_changed_today: list[str] = Field(default_factory=list)
    watch_next: list[str] = Field(default_factory=list)
    bull_case: CaseStatement
    base_case: CaseStatement
    bear_case: CaseStatement
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    data_freshness: FreshnessStatus = "fresh"
