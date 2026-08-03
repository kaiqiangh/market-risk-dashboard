"""AI 分析输出校验测试（pipeline/analysis/validate.py + freshness.py）。

覆盖：双语一致性（market_state/market_regime/confidence/数字/evidence_refs）、
evidence_refs 有效性、新鲜度五态判定。
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
    assert any("数字" in issue or "文本数字" in issue for issue in issues)


def test_list_length_mismatch_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    en = load_analysis(FIXTURES / "analysis.en.json")
    en.watch_next.append("extra item")
    issues = compare_bilingual(zh, en)
    assert any("watch_next 长度" in issue for issue in issues)


def test_evidence_ref_not_in_index_detected() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    facts = FactLayer.model_validate(load("facts.json"))
    zh.evidence_refs[0].value = 999.0  # 与 evidence_index 中的 52.3 不一致
    issues = validate_evidence_refs(zh, facts)
    assert len(issues) == 1
    assert "不存在于" in issues[0]


def test_all_evidence_refs_valid() -> None:
    zh = load_analysis(FIXTURES / "analysis.zh-CN.json")
    facts = FactLayer.model_validate(load("facts.json"))
    assert validate_evidence_refs(zh, facts) == []


# ---------- freshness 五态 ----------

def test_freshness_five_states() -> None:
    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    interval_min = 60  # 期望间隔 60 分钟
    assert evaluate_freshness(None, interval_min, now) == "missing"
    # 30 分钟前 → fresh（≤ 1.5×60=90min）
    assert evaluate_freshness("2026-08-03T11:30:00Z", interval_min, now) == "fresh"
    # 2 小时前 → delayed（1.5×~3×，即 90~180min）
    assert evaluate_freshness("2026-08-03T10:00:00Z", interval_min, now) == "delayed"
    # 4 小时前 → stale（> 3×）
    assert evaluate_freshness("2026-08-03T08:00:00Z", interval_min, now) == "stale"


def test_analysis_freshness_with_facts() -> None:
    facts = FactLayer.model_validate(load("facts.json"))
    # 事实层 10:00 生成，analysis 期望间隔 12h；11:00 判定 → fresh
    status, decision = evaluate_analysis_freshness(
        facts, now=datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)
    )
    assert status == "fresh"
    assert decision == "run"
