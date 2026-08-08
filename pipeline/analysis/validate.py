"""AI analysis output validation (architecture §1.5/§3.4).

Checks:
1. Schema: analysis.*.json must pass AnalysisDataset validation (no implicit fields/NaN/enum/time).
2. evidence_refs: every reference must find an exactly matching entry in the fact layer evidence_index.
3. Bilingual consistency: zh-CN and en must agree on market_state/market_regime/confidence,
   the evidence_refs set, and all numbers in every text; only the language of the prose may differ.

Usage:
    python -m pipeline.analysis.validate --zh public/data/latest/analysis.zh-CN.json \
        --en public/data/latest/analysis.en.json \
        --facts public/data/latest/facts.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

from pipeline.analysis.contract import input_path, output_path
from pipeline.lineage import fact_generation_id, is_valid_fact_generation_id
from pipeline.schemas import AnalysisDataset, EvidenceRef, FactLayer

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def load_analysis(path: Path | str) -> AnalysisDataset:
    """Load and validate a single analysis file (self-describing contract file, parsed directly as AnalysisDataset)."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return AnalysisDataset.model_validate(data)


def collect_evidence_refs(analysis: AnalysisDataset) -> list[EvidenceRef]:
    """Collect all evidence refs referenced in the analysis file (including nested signal/case)."""
    refs: list[EvidenceRef] = list(analysis.evidence_refs)
    for claim in analysis.top_risk_drivers + analysis.supporting_signals + analysis.contradicting_signals:
        refs.extend(claim.evidence_refs)
    for case in (analysis.bull_case, analysis.base_case, analysis.bear_case):
        refs.extend(case.evidence_refs)
    return refs


def _ref_key(ref: EvidenceRef) -> tuple[str, str, str, str]:
    """Evidence normalization key (value normalized to string for stable comparison)."""
    if isinstance(ref.value, float):
        value = f"{ref.value:.6f}"
    else:
        value = str(ref.value)
    return (ref.dataset, ref.path, ref.metric, value)


def validate_evidence_refs(analysis: AnalysisDataset, facts: FactLayer) -> list[str]:
    """Validate that every evidence_ref in analysis can be found in evidence_index. Returns a list of issues."""
    index_keys = {_ref_key(ref) for ref in facts.evidence_index.values()}
    issues: list[str] = []
    for ref in collect_evidence_refs(analysis):
        key = _ref_key(ref)
        if key not in index_keys:
            issues.append(
                f"evidence_ref not found in evidence_index: {ref.dataset}/{ref.path}/{ref.metric}={ref.value!r}"
            )
    return issues


def validate_fact_identity(facts: FactLayer) -> list[str]:
    """Validate that a published fact layer carries its deterministic identity."""
    if not is_valid_fact_generation_id(facts.generation_id):
        return ["facts generation_id missing or malformed"]
    expected = fact_generation_id(facts)
    if facts.generation_id != expected:
        return ["facts generation_id does not match its content"]
    return []


def validate_analysis_lineage(analysis: AnalysisDataset, facts: FactLayer) -> list[str]:
    """Validate one analysis file's reference to the fact layer it claims to have read."""
    if analysis.lineage is None:
        return ["analysis lineage missing"]

    issues = validate_fact_identity(facts)
    if facts.generation_id is not None and analysis.lineage.fact_generation_id != facts.generation_id:
        issues.append("analysis fact_generation_id does not match facts generation_id")
    if analysis.lineage.fact_generated_at != facts.generated_at:
        issues.append("analysis fact_generated_at does not match facts generated_at")
    if analysis.lineage.input_freshness != facts.data_freshness:
        issues.append("analysis input_freshness does not match facts data_freshness")
    return issues


def compare_analysis_lineage(zh: AnalysisDataset, en: AnalysisDataset) -> list[str]:
    """Validate the shared lineage fields of a bilingual pair."""
    if zh.lineage is None and en.lineage is None:
        return ["analysis lineage missing from both language files"]
    if zh.lineage is None or en.lineage is None:
        return ["analysis lineage missing from one language file"]

    issues: list[str] = []
    if zh.lineage.pair_id != en.lineage.pair_id:
        issues.append("analysis pair_id mismatch")
    if zh.lineage.fact_generation_id != en.lineage.fact_generation_id:
        issues.append("analysis fact_generation_id mismatch")
    if zh.lineage.fact_generated_at != en.lineage.fact_generated_at:
        issues.append("analysis fact_generated_at mismatch")
    if zh.lineage.input_freshness != en.lineage.input_freshness:
        issues.append("analysis input_freshness mismatch")
    return issues


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUM_RE.findall(text)]


def _numbers_match(zh_text: str, en_text: str) -> bool:
    """The set of numbers in two texts must match exactly (tolerating 1e-6 rounding)."""
    zh_nums = sorted(_extract_numbers(zh_text))
    en_nums = sorted(_extract_numbers(en_text))
    if len(zh_nums) != len(en_nums):
        return False
    return all(abs(a - b) < 1e-6 for a, b in zip(zh_nums, en_nums))


def compare_bilingual(zh: AnalysisDataset, en: AnalysisDataset) -> list[str]:
    """Bilingual consistency validation (architecture §3.4). Returns a list of issues; empty list = pass."""
    issues: list[str] = []

    if zh.market_state != en.market_state:
        issues.append(f"market_state mismatch: zh={zh.market_state!r} en={en.market_state!r}")
    if zh.market_regime != en.market_regime:
        issues.append(f"market_regime mismatch: zh={zh.market_regime!r} en={en.market_regime!r}")
    if abs(zh.confidence - en.confidence) > 1e-9:
        issues.append(f"confidence mismatch: zh={zh.confidence} en={en.confidence}")

    zh_ref_keys = sorted(_ref_key(r) for r in collect_evidence_refs(zh))
    en_ref_keys = sorted(_ref_key(r) for r in collect_evidence_refs(en))
    if zh_ref_keys != en_ref_keys:
        issues.append(f"evidence_refs set mismatch: zh={len(zh_ref_keys)} en={len(en_ref_keys)}")

    # Parallel list lengths must match (structural equivalence)
    list_pairs: list[tuple[str, list[str], list[str]]] = [
        ("top_risk_drivers", zh.top_risk_drivers, en.top_risk_drivers),
        ("supporting_signals", zh.supporting_signals, en.supporting_signals),
        ("contradicting_signals", zh.contradicting_signals, en.contradicting_signals),
        ("what_changed_today", zh.what_changed_today, en.what_changed_today),
        ("watch_next", zh.watch_next, en.watch_next),
        ("bull_case.points", zh.bull_case.points, en.bull_case.points),
        ("base_case.points", zh.base_case.points, en.base_case.points),
        ("bear_case.points", zh.bear_case.points, en.bear_case.points),
    ]
    for field, zh_list, en_list in list_pairs:
        if len(zh_list) != len(en_list):
            issues.append(f"{field} length mismatch: zh={len(zh_list)} en={len(en_list)}")

    # Numbers in text fields must match (summary/title/points/claim/watch_next)
    text_pairs: list[tuple[str, str]] = [
        (zh.summary, en.summary),
        (zh.bull_case.title, en.bull_case.title),
        (zh.base_case.title, en.base_case.title),
        (zh.bear_case.title, en.bear_case.title),
    ]
    text_pairs += list(zip(zh.bull_case.points, en.bull_case.points))
    text_pairs += list(zip(zh.base_case.points, en.base_case.points))
    text_pairs += list(zip(zh.bear_case.points, en.bear_case.points))
    text_pairs += list(zip(zh.what_changed_today, en.what_changed_today))
    text_pairs += list(zip(zh.watch_next, en.watch_next))
    for claim_zh, claim_en in zip(zh.top_risk_drivers + zh.supporting_signals + zh.contradicting_signals,
                                  en.top_risk_drivers + en.supporting_signals + en.contradicting_signals):
        text_pairs.append((claim_zh.claim, claim_en.claim))

    for i, (zh_text, en_text) in enumerate(text_pairs):
        if not _numbers_match(zh_text, en_text):
            issues.append(f"text number mismatch (text group {i + 1}): zh={zh_text!r} en={en_text!r}")

    return issues


def validate_analysis_pair(
    zh_path: Path | str,
    en_path: Path | str,
    facts_path: Path | str | None = None,
) -> tuple[list[str], AnalysisDataset, AnalysisDataset]:
    """Full validation: schema + evidence_refs + bilingual consistency. Returns (issues, zh, en)."""
    zh = load_analysis(zh_path)
    en = load_analysis(en_path)

    if zh.language != "zh-CN" or en.language != "en":
        raise ValueError(f"language mismatch: zh.language={zh.language!r} en.language={en.language!r}")

    issues: list[str] = []

    if facts_path is not None:
        facts = FactLayer.model_validate(json.loads(Path(facts_path).read_text(encoding="utf-8")))
        issues.extend(validate_evidence_refs(zh, facts))
        issues.extend(validate_evidence_refs(en, facts))

    issues.extend(compare_bilingual(zh, en))
    return issues, zh, en


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI analysis output validation (schema + evidence_refs + bilingual consistency)")
    parser.add_argument("--zh", type=Path, default=None, help="analysis.zh-CN.json (default contract path)")
    parser.add_argument("--en", type=Path, default=None, help="analysis.en.json (default contract path)")
    parser.add_argument("--facts", type=Path, default=None, help="facts.json (default contract path)")
    args = parser.parse_args(argv)

    zh_path = args.zh or output_path("analysis_zh")
    en_path = args.en or output_path("analysis_en")
    facts_path = args.facts or input_path("facts")

    if not zh_path.exists() or not en_path.exists():
        print(f"[validate] analysis file missing: {zh_path} / {en_path} (validate after AI automation output)", file=sys.stderr)
        return 1

    try:
        issues, _, _ = validate_analysis_pair(zh_path, en_path, facts_path if facts_path.exists() else None)
    except Exception as exc:  # noqa: BLE001 — CLI top-level catch and print
        print(f"[validate] validation failed (schema error): {exc}", file=sys.stderr)
        return 1

    if issues:
        print("[validate] failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("[validate] passed: schema ✓ evidence_refs ✓ bilingual consistency ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
