"""事实层契约（架构 §3.3，AI 输入契约，语言无关的确定性事实）。

- facts.json 为自描述契约文件（含 generated_at/schema_version），按 §3.3 直接使用
  FactLayer 模型解析（与 analysis.*.json 一致，不额外包裹 BaseEnvelope，见 contract.py 说明）。
- evidence_index: dict[str, EvidenceRef]；AI 只能引用该索引中的证据。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime
from .risk import RiskModelResult


class EvidenceRef(ContractModel):
    """可被 AI 引用的单条证据。"""

    dataset: str = Field(min_length=1, description='如 "macro" / "equities" / "risk"')
    path: str = Field(min_length=1, description='如 "payload.liquidity[3]"')
    metric: str = Field(min_length=1)
    value: float | str
    updated_at: UTCDateTime | None = None


class FactLayer(ContractModel):
    """事实层（facts.json）。"""

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1)
    data_freshness: dict[str, FreshnessStatus] = Field(default_factory=dict)
    risk: RiskModelResult
    macro_summary: dict[str, Any] = Field(default_factory=dict)
    market_summary: dict[str, Any] = Field(default_factory=dict)
    news_top: list[dict[str, Any]] = Field(default_factory=list, description="重要性 Top 15 新闻")
    calendar_next7d: list[dict[str, Any]] = Field(default_factory=list, description="未来 7 天事件")
    evidence_index: dict[str, EvidenceRef] = Field(default_factory=dict)
