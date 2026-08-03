"""分析新鲜度检查（架构 §8.5 五态语义；供 AI 自动化决策是否跳过）。

五态判定复用 pipeline/validation/freshness.py（管道统一判定，架构 §8.4）。

用法：
    python -m pipeline.analysis.freshness [--facts path] [--interval-min 720]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pipeline.analysis.contract import expected_interval_minutes, input_path
from pipeline.schemas import FactLayer, FreshnessStatus
from pipeline.validation.freshness import evaluate_freshness

AnalysisDecision = Literal["run", "skip_missing", "run_stale", "run_degraded"]


def evaluate_analysis_freshness(facts: FactLayer, now: datetime | None = None) -> tuple[FreshnessStatus, AnalysisDecision]:
    """综合判定：时间维度 + 事实层数据质量。返回 (status, 决策)。"""
    time_status = evaluate_freshness(facts.generated_at, expected_interval_minutes("analysis"), now)

    degraded_datasets = [
        key for key, status in facts.data_freshness.items() if status in ("degraded", "missing")
    ]

    if time_status == "missing":
        return "missing", "skip_missing"
    if degraded_datasets:
        return "degraded", "run_degraded"
    if time_status == "stale":
        return "stale", "run_stale"
    return time_status, "run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 分析新鲜度检查")
    parser.add_argument("--facts", type=Path, default=None, help="facts.json 路径（默认契约路径）")
    parser.add_argument("--interval-min", type=int, default=None, help="覆盖 analysis 期望间隔（分钟）")
    args = parser.parse_args(argv)

    facts_path = args.facts or input_path("facts")
    if not facts_path.exists():
        print("[freshness] missing（事实层不存在） decision=skip_missing", file=sys.stderr)
        return 0

    facts = FactLayer.model_validate(json.loads(facts_path.read_text(encoding="utf-8")))
    status, decision = evaluate_analysis_freshness(facts)
    interval = args.interval_min or expected_interval_minutes("analysis")
    print(
        f"[freshness] status={status} decision={decision} "
        f"generated_at={facts.generated_at} expected_interval_min={interval}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
