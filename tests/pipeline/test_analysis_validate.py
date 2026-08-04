"""AI analysis output validation tests (pipeline/analysis/validate.py + freshness.py).

Covers: bilingual consistency (market_state/market_regime/confidence/numbers/evidence_refs),
evidence_refs validity, five-state freshness determination.

Since #73 the suite builds its own inputs: the analysis pair and facts document come from
:mod:`tests.pipeline.factories` (bilingually consistent by construction), not from the deleted
static fixture bundle. The hand-written goldens are validated separately in test_schemas.py and
by tests/frontend/schemas.test.ts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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
from tests.pipeline.factories import DEFAULT_NOW, make_analysis, make_facts


def _write_factory_pair(root: Path) -> tuple[Path, Path, Path]:
    """Write a bilingually consistent analysis pair + facts document under `root`."""
    zh_path = root / "analysis.zh-CN.json"
    en_path = root / "analysis.en.json"
    facts_path = root / "facts.json"
    zh_path.write_text(json.dumps(make_analysis(language="zh-CN"), ensure_ascii=False), encoding="utf-8")
    en_path.write_text(json.dumps(make_analysis(language="en"), ensure_ascii=False), encoding="utf-8")
    facts_path.write_text(json.dumps(make_facts(), ensure_ascii=False), encoding="utf-8")
    return zh_path, en_path, facts_path


@pytest.fixture()
def analysis_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    return _write_factory_pair(tmp_path)


def _zh_and_en(analysis_pair: tuple[Path, Path, Path]):
    zh_path, en_path, _facts_path = analysis_pair
    return load_analysis(zh_path), load_analysis(en_path)


def test_valid_pair_passes(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh_path, en_path, facts_path = analysis_pair
    issues, zh, en = validate_analysis_pair(zh_path, en_path, facts_path)
    assert issues == []


def test_market_state_mismatch_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh, en = _zh_and_en(analysis_pair)
    zh.market_state = "high_risk"
    issues = compare_bilingual(zh, en)
    assert any("market_state" in issue for issue in issues)


def test_market_regime_mismatch_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh, en = _zh_and_en(analysis_pair)
    en.market_regime = "stagflation"
    issues = compare_bilingual(zh, en)
    assert any("market_regime" in issue for issue in issues)


def test_confidence_mismatch_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh, en = _zh_and_en(analysis_pair)
    zh.confidence = 0.5
    issues = compare_bilingual(zh, en)
    assert any("confidence" in issue for issue in issues)


def test_number_mismatch_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh, en = _zh_and_en(analysis_pair)
    # The factory pair is consistent (both texts carry 62.5); changing one side is the defect.
    en.summary = en.summary.replace("62.5", "99.9")
    issues = compare_bilingual(zh, en)
    assert any("text number" in issue for issue in issues)


def test_list_length_mismatch_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh, en = _zh_and_en(analysis_pair)
    en.watch_next.append("extra item")
    issues = compare_bilingual(zh, en)
    assert any("watch_next length" in issue for issue in issues)


def test_evidence_ref_not_in_index_detected(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh_path, _en_path, facts_path = analysis_pair
    zh = load_analysis(zh_path)
    facts = FactLayer.model_validate(json.loads(facts_path.read_text(encoding="utf-8")))
    zh.evidence_refs[0].value = 999.0  # inconsistent with the evidence_index value
    issues = validate_evidence_refs(zh, facts)
    assert len(issues) == 1
    assert "not found in" in issues[0]


def test_all_evidence_refs_valid(analysis_pair: tuple[Path, Path, Path]) -> None:
    zh_path, _en_path, facts_path = analysis_pair
    zh = load_analysis(zh_path)
    facts = FactLayer.model_validate(json.loads(facts_path.read_text(encoding="utf-8")))
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
    facts = FactLayer.model_validate(make_facts())
    # fact layer generated at DEFAULT_NOW; judged 1h later within the 12h analysis interval → fresh
    later = DEFAULT_NOW + timedelta(hours=1)
    status, decision = evaluate_analysis_freshness(facts, now=later)
    assert status == "fresh"
    assert decision == "run"
