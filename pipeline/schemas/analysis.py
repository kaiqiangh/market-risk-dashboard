"""AI 分析输出契约（架构 §3.4，自动化产出 analysis.zh-CN.json / analysis.en.json）。

- 文件为自描述契约（含 schema_version/generated_at/language），不额外包裹 BaseEnvelope。
- 双语一致性（架构 §1.5/§3.4）：market_state/market_regime/confidence/evidence_refs
  与所有数字必须在 zh-CN 与 en 中完全一致；仅表达文本语言可不同。
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime
from .factlayer import EvidenceRef

AnalysisLanguage = Literal["zh-CN", "en"]


class SignalClaim(ContractModel):
    """一条带证据的结论。"""

    claim: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class CaseStatement(ContractModel):
    """一个情景（牛市/基准/熊市）的陈述。"""

    title: str = Field(min_length=1)
    points: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class AnalysisDataset(ContractModel):
    """AI 双语简报（单一语言文件）。"""

    schema_version: str = Field(min_length=1)
    generated_at: UTCDateTime
    language: AnalysisLanguage
    market_state: str = Field(min_length=1, description="与风险等级一致（risk_level）")
    market_regime: str = Field(min_length=1, description="与事实层 regime 一致")
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
