"""Fact layer → AI bilingual prompt template (architecture §1.5).

Usage:
    python -m pipeline.analysis.build_prompt --lang zh-CN
    python -m pipeline.analysis.build_prompt --lang en --facts path/to/facts.json
Output is a plain-text prompt (stdout or --out writes to file).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from pipeline.analysis.contract import SUPPORTED_LANGUAGES, input_path
from pipeline.schemas import AnalysisDataset, FactLayer

_SYSTEM_TASKS: dict[str, str] = {
    "zh-CN": (
        "你是全球市场风险情报看板（Market Risk Dashboard）的资深市场分析师。"
        "基于给定的事实层，撰写一份中文市场风险简报。"
        "注意：财联社/华尔街见闻等中文新闻源经 RSSHub 第三方聚合中转（trust: relay），"
        "属于二手聚合信息，引用时按行业资讯对待，勿当作一手官方信源。"
    ),
    "en": (
        "You are a senior market analyst for the Market Risk Dashboard. "
        "Write an English market risk brief based on the given fact layer. "
        "Note: the Chinese news sources (CLS / Wall Street CN) are relayed through the "
        "third-party RSSHub aggregator (trust: relay) — treat them as second-hand "
        "industry aggregation, not first-party official statements."
    ),
}

_OUTPUT_HEADINGS: dict[str, str] = {
    "zh-CN": "输出 JSON；下面的 JSON Schema 由 AnalysisDataset 模型生成：",
    "en": "Output JSON; the JSON Schema below is generated from the AnalysisDataset model:",
}


def _output_contract(lang: str) -> str:
    """Render the output contract from the Python model so prompt and schema cannot drift."""
    return f"{_OUTPUT_HEADINGS[lang]}\n{json.dumps(AnalysisDataset.model_json_schema(), ensure_ascii=False, indent=2)}"

_CITATION_RULES: dict[str, str] = {
    "zh-CN": (
        "证据规则：每个结论必须携带 evidence_refs；只允许引用下方 evidence_index 中存在的条目"
        "（dataset/path/metric/value 需完全一致）。不得编造证据；无证据支持的判断归入 summary 而非结论列表。"
        "所有数字（风险分、百分比、点位）必须与事实层一致。"
    ),
    "en": (
        "Evidence rules: every claim must carry evidence_refs; you may ONLY cite entries present in "
        "the evidence_index below (dataset/path/metric/value must match exactly). Never fabricate "
        "evidence; unsupported judgments go into summary, not the claim lists. All numbers (risk "
        "scores, percentages, levels) must match the fact layer."
    ),
}

_LANGUAGE_RULES: dict[str, str] = {
    "zh-CN": (
        "语言约束：本简报所有文案字段——summary、top_risk_drivers / supporting_signals / "
        "contradicting_signals 中每条 claim、bull_case / base_case / bear_case 的 title 与 points、"
        "what_changed_today、watch_next——必须全部使用中文，且不得混入英文句子（专有名词/代码/数字除外）。"
    ),
    "en": (
        "Language constraint (HARD): EVERY prose field in this brief — summary, every claim in "
        "top_risk_drivers / supporting_signals / contradicting_signals, every bull_case / base_case / "
        "bear_case title and points, what_changed_today, and watch_next — MUST be written in English. "
        "Do NOT leave any field in Chinese. Chinese characters anywhere in the English output are a "
        "hard failure and will be rejected by validation. Proper nouns, tickers, and numbers may stay "
        "as-is; prose must be English."
    ),
}


_THEME_LABELS: dict[str, dict[str, str]] = {}


def _theme_labels(lang: str) -> dict[str, str]:
    """Sector/theme labels for a language — read from the SAME per-locale file the
    frontend renders (one source, #98: the #93/#102 label removal tracked the prompt-side
    English-label need here; the zh-CN brief resolves the zh labels, not a leak of EN).

    A missing/unreadable file degrades to raw keys but is PUBLISHED as a warning
    (ADR-0004 / §8.8: never swallow silently) — the brief still works, it just loses
    labels.
    """
    if lang in _THEME_LABELS:
        return _THEME_LABELS[lang]
    labels: dict[str, str] = {}
    path = Path(__file__).resolve().parents[2] / "src" / "i18n" / "locales" / lang / "themes.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[build_prompt] themes.json unreadable for %s (%s) — sector labels fall back to raw keys", lang, exc)
        data = {}
    for key, value in data.items():
        if isinstance(value, str):
            labels[key] = value
    _THEME_LABELS[lang] = labels
    return labels


_SECTOR_HEADING: dict[str, str] = {"en": "Sector performance (1d)", "zh-CN": "板块表现（1日）"}


def _render_facts(facts: FactLayer, lang: str) -> str:
    """Fact layer → text summary (labels resolved per language — the section heading and
    the sector/theme names follow the brief's language; all numbers stay identical)."""
    risk = facts.risk
    dims = "\n".join(
        f"  - {d.key}: score={d.score:.1f} weight={d.weight} effective_weight={d.effective_weight:.1f} "
        f"coverage={d.coverage:.2f} trend={d.trend}"
        for d in risk.dimensions
    )
    drivers = "\n".join(
        f"  - {d.label} (dim={d.dimension_key}, indicator={d.indicator_key}): contribution={d.contribution:.2f}"
        for d in risk.top_drivers
    )
    evidence = "\n".join(
        f"  - [{key}] dataset={ref.dataset} path={ref.path} metric={ref.metric} value={ref.value}"
        for key, ref in facts.evidence_index.items()
    )
    labels = _theme_labels(lang)
    sector_rows = [
        row for row in facts.market_summary.get("sector_performance", [])
        if isinstance(row, dict) and isinstance(row.get("change_1d"), (int, float))
    ]
    sector_lines = "\n".join(
        f"  - {labels.get(str(row['key']), str(row['key']))}: {row['change_1d']:+.2f}%"
        for row in sector_rows
    ) if sector_rows else "  (none)"

    return f"""## Fact Layer (generated_at={facts.generated_at}, schema_version={facts.schema_version})

### Risk snapshot
- total_score={risk.total_score:.1f} risk_level={risk.risk_level} regime={risk.regime}
- trend_1d={risk.trend_1d} trend_1w={risk.trend_1w} trend_1m={risk.trend_1m}
- confidence={risk.confidence:.2f} confidence_factors={json.dumps(risk.confidence_factors, ensure_ascii=False)}
- regime_evidence={json.dumps(risk.regime_evidence, ensure_ascii=False)}

### Dimensions
{dims}

### Top drivers
{drivers}

### Macro summary
{json.dumps(facts.macro_summary, ensure_ascii=False)}

### Market summary
{json.dumps(facts.market_summary, ensure_ascii=False)}

### {_SECTOR_HEADING[lang]}
{sector_lines}

### Top news (Top 15 by importance)
{json.dumps(facts.news_top[:15], ensure_ascii=False)}

### Calendar next 7d
{json.dumps(facts.calendar_next7d, ensure_ascii=False)}

### Evidence index (only citable evidence)
{evidence if evidence else '  (empty)'}
"""


def build_prompt(facts: FactLayer, lang: str) -> str:
    """Assemble the full prompt (system + fact layer + output contract + evidence rules)."""
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {lang!r}, options: {SUPPORTED_LANGUAGES}")
    system = _SYSTEM_TASKS[lang]
    output_contract = _output_contract(lang)
    citation = _CITATION_RULES[lang]
    language_rule = _LANGUAGE_RULES[lang]
    return (
        f"# System\n{system}\n\n"
        f"# Input\n{_render_facts(facts, lang)}\n"
        f"# Output contract\n{output_contract}\n"
        f"# Rules\n{citation}\n"
        f"# Language rule\n{language_rule}\n"
    )


def load_facts(path: Path | str) -> FactLayer:
    """Load and validate facts.json (self-describing contract file, parsed directly as FactLayer)."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return FactLayer.model_validate(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build AI analysis prompt")
    parser.add_argument("--lang", choices=list(SUPPORTED_LANGUAGES), required=True)
    parser.add_argument("--facts", type=Path, default=None, help="facts.json path (default contract path)")
    parser.add_argument("--out", type=Path, default=None, help="write to file (default stdout)")
    args = parser.parse_args(argv)

    facts_path = args.facts or input_path("facts")
    if not facts_path.exists():
        print(f"[build_prompt] fact layer not found: {facts_path} (available once T03 produces a real facts.json)", file=sys.stderr)
        return 1

    facts = load_facts(facts_path)
    prompt = build_prompt(facts, args.lang)
    if args.out:
        args.out.write_text(prompt, encoding="utf-8")
        print(f"[build_prompt] written to {args.out}")
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
