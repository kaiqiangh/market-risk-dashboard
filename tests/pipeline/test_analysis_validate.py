"""AI analysis output validation tests (pipeline/analysis/validate.py + freshness.py).

Covers: bilingual consistency (market_state/market_regime/confidence/numbers/evidence_refs),
evidence_refs validity, five-state freshness determination.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.analysis.freshness import evaluate_analysis_freshness, evaluate_freshness
from pipeline.analysis.validate import (
    compare_bilingual,
    load_analysis,
    validate_analysis_pair,
    validate_evidence_refs,
)
from pipeline.schemas import FactLayer

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_valid_pair_passes() -> None:
    issues, zh, en = validate_analysis_pair(
        FIXTURES / "analysis.zh-CN.json",
        FIXTURES / "analysis.en.json",
        FIXTURES / "facts.json",
    )
    assert issues == []


def test_market_state_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    zh.market_state = "high_risk"
    issues = compare_bilingual(zh, en)
    assert any("market_state" in issue for issue in issues)


def test_market_regime_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    en.market_regime = "stagflation"
    issues = compare_bilingual(zh, en)
    assert any("market_regime" in issue for issue in issues)


def test_confidence_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    zh.confidence = 0.5
    issues = compare_bilingual(zh, en)
    assert any("confidence" in issue for issue in issues)


def test_number_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    en.summary = en.summary.replace("52.3", "99.9")
    issues = compare_bilingual(zh, en)
    assert any("text number" in issue for issue in issues)


def test_list_length_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    en.watch_next.append("extra item")
    issues = compare_bilingual(zh, en)
    assert any("watch_next length" in issue for issue in issues)


def test_evidence_ref_not_in_index_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    facts = FactLayer.model_validate(load("facts.json"))
    zh.evidence_refs[0].value = 999.0  # inconsistent with 52.3 in evidence_index
    issues = validate_evidence_refs(zh, facts)
    assert len(issues) == 1
    assert "not found in" in issues[0]


def test_all_evidence_refs_valid() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    facts = FactLayer.model_validate(load("facts.json"))
    assert validate_evidence_refs(zh, facts) == []


# ---------- freshness five states ----------

def test_freshness_five_states() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    interval_min = 60  # expected interval 60 minutes
    assert evaluate_freshness(None, interval_min, now) == "missing"
    # 30 minutes ago → fresh (≤ 1.5×60=90min)
    assert evaluate_freshness("2026-08-03T11:30:00Z", interval_min, now) == "fresh"
    # 2 hours ago → delayed (1.5×~3×, i.e. 90~180min)
    assert evaluate_freshness("2026-08-03T10:00:00Z", interval_min, now) == "delayed"
    # 4 hours ago → stale (> 3×)
    assert evaluate_freshness("2026-08-03T08:00:00Z", interval_min, now) == "stale"


def test_analysis_freshness_with_facts() -> None:
    facts = FactLayer.model_validate(load("facts.json"))
    # fact layer generated at 10:00, analysis expected interval 12h; judged at 11:00 → fresh
    status, decision = evaluate_analysis_freshness(
        facts, now=datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)
    )
    assert status == "fresh"
    assert decision == "run"
