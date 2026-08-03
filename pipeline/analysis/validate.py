"""AI 分析输出校验（架构 §1.5/§3.4）。

校验内容：
1. Schema：analysis.*.json 必须通过 AnalysisDataset 校验（禁隐式字段/NaN/枚举/时间）。
2. evidence_refs：每个引用必须能在事实层 evidence_index 中找到完全一致的条目。
3. 双语一致性：zh-CN 与 en 的 market_state/market_regime/confidence、
   evidence_refs 集合、以及所有文本中的数字必须完全一致；仅表达语言可不同。

用法：
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
from pipeline.schemas import AnalysisDataset, EvidenceRef, FactLayer

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def load_analysis(path: Path | str) -> AnalysisDataset:
    """加载并校验单个分析文件（自描述契约文件，直接解析 AnalysisDataset）。"""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return AnalysisDataset.model_validate(data)


def collect_evidence_refs(analysis: AnalysisDataset) -> list[EvidenceRef]:
    """汇总分析文件中所有被引用的证据（含嵌套 signal/case）。"""
    refs: list[EvidenceRef] = list(analysis.evidence_refs)
    for claim in analysis.top_risk_drivers + analysis.supporting_signals + analysis.contradicting_signals:
        refs.extend(claim.evidence_refs)
    for case in (analysis.bull_case, analysis.base_case, analysis.bear_case):
        refs.extend(case.evidence_refs)
    return refs


def _ref_key(ref: EvidenceRef) -> tuple[str, str, str, str]:
    """证据归一化键（value 统一为字符串以稳定比较）。"""
    if isinstance(ref.value, float):
        value = f"{ref.value:.6f}"
    else:
        value = str(ref.value)
    return (ref.dataset, ref.path, ref.metric, value)


def validate_evidence_refs(analysis: AnalysisDataset, facts: FactLayer) -> list[str]:
    """校验 analysis 中每个 evidence_ref 都能在 evidence_index 中找到。返回问题列表。"""
    index_keys = {_ref_key(ref) for ref in facts.evidence_index.values()}
    issues: list[str] = []
    for ref in collect_evidence_refs(analysis):
        key = _ref_key(ref)
        if key not in index_keys:
            issues.append(
                f"evidence_ref 不存在于 evidence_index: {ref.dataset}/{ref.path}/{ref.metric}={ref.value!r}"
            )
    return issues


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUM_RE.findall(text)]


def _numbers_match(zh_text: str, en_text: str) -> bool:
    """两段文本中的数字集合必须完全一致（容忍 1e-6 舍入）。"""
    zh_nums = sorted(_extract_numbers(zh_text))
    en_nums = sorted(_extract_numbers(en_text))
    if len(zh_nums) != len(en_nums):
        return False
    return all(abs(a - b) < 1e-6 for a, b in zip(zh_nums, en_nums))


def compare_bilingual(zh: AnalysisDataset, en: AnalysisDataset) -> list[str]:
    """双语一致性校验（架构 §3.4）。返回问题列表；空列表 = 通过。"""
    issues: list[str] = []

    if zh.market_state != en.market_state:
        issues.append(f"market_state 不一致: zh={zh.market_state!r} en={en.market_state!r}")
    if zh.market_regime != en.market_regime:
        issues.append(f"market_regime 不一致: zh={zh.market_regime!r} en={en.market_regime!r}")
    if abs(zh.confidence - en.confidence) > 1e-9:
        issues.append(f"confidence 不一致: zh={zh.confidence} en={en.confidence}")

    zh_ref_keys = sorted(_ref_key(r) for r in collect_evidence_refs(zh))
    en_ref_keys = sorted(_ref_key(r) for r in collect_evidence_refs(en))
    if zh_ref_keys != en_ref_keys:
        issues.append(f"evidence_refs 集合不一致: zh={len(zh_ref_keys)} en={len(en_ref_keys)}")

    # 并行列表长度必须一致（结构对等）
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
            issues.append(f"{field} 长度不一致: zh={len(zh_list)} en={len(en_list)}")

    # 文本字段中的数字必须一致（summary/title/points/claim/watch_next）
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
            issues.append(f"文本数字不一致（第 {i + 1} 组文本）: zh={zh_text!r} en={en_text!r}")

    return issues


def validate_analysis_pair(
    zh_path: Path | str,
    en_path: Path | str,
    facts_path: Path | str | None = None,
) -> tuple[list[str], AnalysisDataset, AnalysisDataset]:
    """全量校验：schema + evidence_refs + 双语一致性。返回 (issues, zh, en)。"""
    zh = load_analysis(zh_path)
    en = load_analysis(en_path)

    if zh.language != "zh-CN" or en.language != "en":
        raise ValueError(f"语言不匹配: zh.language={zh.language!r} en.language={en.language!r}")

    issues: list[str] = []

    if facts_path is not None:
        facts = FactLayer.model_validate(json.loads(Path(facts_path).read_text(encoding="utf-8")))
        issues.extend(validate_evidence_refs(zh, facts))
        issues.extend(validate_evidence_refs(en, facts))

    issues.extend(compare_bilingual(zh, en))
    return issues, zh, en


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 分析输出校验（schema + evidence_refs + 双语一致性）")
    parser.add_argument("--zh", type=Path, default=None, help="analysis.zh-CN.json（默认契约路径）")
    parser.add_argument("--en", type=Path, default=None, help="analysis.en.json（默认契约路径）")
    parser.add_argument("--facts", type=Path, default=None, help="facts.json（默认契约路径）")
    args = parser.parse_args(argv)

    zh_path = args.zh or output_path("analysis_zh")
    en_path = args.en or output_path("analysis_en")
    facts_path = args.facts or input_path("facts")

    if not zh_path.exists() or not en_path.exists():
        print(f"[validate] 分析文件缺失: {zh_path} / {en_path}（AI 自动化产出后校验）", file=sys.stderr)
        return 1

    try:
        issues, _, _ = validate_analysis_pair(zh_path, en_path, facts_path if facts_path.exists() else None)
    except Exception as exc:  # noqa: BLE001 — CLI 顶层捕获并打印
        print(f"[validate] 校验失败（schema 错误）: {exc}", file=sys.stderr)
        return 1

    if issues:
        print("[validate] 未通过：")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("[validate] 通过：schema ✓ evidence_refs ✓ 双语一致性 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
