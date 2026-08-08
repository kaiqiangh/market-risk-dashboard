"""Fact layer contract (architecture §3.3; AI input contract, language-neutral deterministic facts).

- facts.json is a self-describing contract file (carries generated_at/schema_version), parsed directly
  with the FactLayer model per §3.3 (like analysis.*.json, not wrapped in BaseEnvelope; see contract.py).
- evidence_index: dict[str, EvidenceRef]; the AI may only cite evidence in this index.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .envelope import ContractModel, FreshnessStatus, UTCDateTime
from .risk import RiskModelResult


class EvidenceRef(ContractModel):
    """A single piece of evidence that can be cited by the AI."""

    dataset: str = Field(min_length=1, description='e.g. "macro" / "equities" / "risk"')
    path: str = Field(min_length=1, description='e.g. "payload.liquidity[3]"')
    metric: str = Field(min_length=1)
    value: float | str
    updated_at: UTCDateTime | None = None


class FactLayer(ContractModel):
    """Fact layer (facts.json)."""

    generated_at: UTCDateTime
    schema_version: str = Field(min_length=1)
    # Optional for backward-compatible parsing; publication validation must reject a missing
    # identity as a fresh AI input. New fact-layer builds always populate this field.
    generation_id: str | None = Field(default=None, min_length=71, pattern=r"^sha256:[0-9a-f]{64}$")
    data_freshness: dict[str, FreshnessStatus] = Field(default_factory=dict)
    risk: RiskModelResult
    macro_summary: dict[str, Any] = Field(default_factory=dict)
    market_summary: dict[str, Any] = Field(default_factory=dict)
    news_top: list[dict[str, Any]] = Field(default_factory=list, description="Top 15 news by importance")
    calendar_next7d: list[dict[str, Any]] = Field(default_factory=list, description="events in the next 7 days")
    evidence_index: dict[str, EvidenceRef] = Field(default_factory=dict)
