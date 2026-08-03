"""Fact layer → AI bilingual prompt template (architecture §1.5).

Usage:
    python -m pipeline.analysis.build_prompt --lang zh-CN
    python -m pipeline.analysis.build_prompt --lang en --facts path/to/facts.json
Output is a plain-text prompt (stdout or --out writes to file).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.analysis.contract import SCHEMA_VERSION, SUPPORTED_LANGUAGES, input_path
from pipeline.schemas import FactLayer

_SYSTEM_TASKS: dict[str, str] = {
    "zh-CN": (
        "你是全球市场风险情报看板（Market Risk Dashboard）的资深市场分析师。"
        "基于给定的事实层，撰写一份中文市场风险简报。"
    ),
    "en": (
        "You are a senior market analyst for the Market Risk Dashboard. "
        "Write an English market risk brief based on the given fact layer."
    ),
}

_OUTPUT_CONTRACT: dict[str, str] = {
    "zh-CN": """输出 JSON（与 AnalysisDataset 契约一致，字段名 snake_case）：
{
  "schema_version": "%s",
  "generated_at": "<当前 UTC ISO8601 Z>",
  "language": "zh-CN",
  "market_state": "<与事实层 risk.risk_level 完全一致>",
  "market_regime": "<与事实层 risk.regime 完全一致>",
  "summary": "<3-5 句总体判断>",
  "top_risk_drivers": [{"claim": "...", "evidence_refs": [{"dataset": "...", "path": "...", "metric": "...", "value": ...}]}],
  "supporting_signals": [{"claim": "...", "evidence_refs": [...]}],
  "contradicting_signals": [{"claim": "...", "evidence_refs": [...]}],
  "what_changed_today": ["..."],
  "watch_next": ["..."],
  "bull_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "base_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "bear_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "confidence": <0-1>,
  "evidence_refs": [...],
  "data_freshness": "<fresh|delayed|stale|missing|degraded>"
}""",
    "en": """Output JSON (AnalysisDataset contract, snake_case field names):
{
  "schema_version": "%s",
  "generated_at": "<current UTC ISO8601 Z>",
  "language": "en",
  "market_state": "<must equal fact layer risk.risk_level>",
  "market_regime": "<must equal fact layer risk.regime>",
  "summary": "<3-5 sentence overall assessment>",
  "top_risk_drivers": [{"claim": "...", "evidence_refs": [{"dataset": "...", "path": "...", "metric": "...", "value": ...}]}],
  "supporting_signals": [{"claim": "...", "evidence_refs": [...]}],
  "contradicting_signals": [{"claim": "...", "evidence_refs": [...]}],
  "what_changed_today": ["..."],
  "watch_next": ["..."],
  "bull_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "base_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "bear_case": {"title": "...", "points": ["..."], "evidence_refs": [...]},
  "confidence": <0-1>,
  "evidence_refs": [...],
  "data_freshness": "<fresh|delayed|stale|missing|degraded>"
}""",
}

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


def _render_facts(facts: FactLayer) -> str:
    """Fact layer → text summary (deterministic, language-neutral)."""
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

### Top news (Top 15 by importance)
{json.dumps(facts.news_top, ensure_ascii=False)}

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
    output_contract = _OUTPUT_CONTRACT[lang] % SCHEMA_VERSION
    citation = _CITATION_RULES[lang]
    return (
        f"# System\n{system}\n\n"
        f"# Input\n{_render_facts(facts)}\n"
        f"# Output contract\n{output_contract}\n"
        f"# Rules\n{citation}\n"
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
