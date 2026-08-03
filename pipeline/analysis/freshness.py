"""Analysis freshness check (architecture §8.5 five-state semantics; used by AI automation to decide whether to skip).

Five-state determination reuses pipeline/validation/freshness.py (unified pipeline determination, architecture §8.4).

Usage:
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
    """Combined determination: time dimension + fact layer data quality. Returns (status, decision)."""
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
    parser = argparse.ArgumentParser(description="AI analysis freshness check")
    parser.add_argument("--facts", type=Path, default=None, help="facts.json path (default contract path)")
    parser.add_argument("--interval-min", type=int, default=None, help="override the analysis expected interval (minutes)")
    args = parser.parse_args(argv)

    facts_path = args.facts or input_path("facts")
    if not facts_path.exists():
        print("[freshness] missing (fact layer not found) decision=skip_missing", file=sys.stderr)
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
