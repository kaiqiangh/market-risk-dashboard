#!/usr/bin/env python3
"""Publish a Global Risk Score weight-balance audit.

Reads the shipped risk-model config and the published risk history, reports how the
*configured* dimension weights compare with the score's actual behaviour, and writes a JSON
artifact for review.

  python scripts/risk_weight_audit.py
  python scripts/risk_weight_audit.py --out artifacts/risk/weight-audit.json

Exit status is 1 when a configured indicator resolves to no scoring path (it would carry its
weight as a constant on every run) and 0 otherwise — the same "fail loudly on a silent
input" posture as ``scripts/check_fallbacks.py``. This script is a diagnostic and is not part
of the CI gate set; it is meant to be run when the risk model is reviewed or changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.risk.weight_audit import audit, blocking_findings, render  # noqa: E402


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_risk_model(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _history_rows(raw: object) -> list[dict]:
    """Accept both the published list shape and a {"rows": [...]} wrapper."""
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, dict) and isinstance(raw.get("rows"), list):
        return [row for row in raw["rows"] if isinstance(row, dict)]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Global Risk Score weight balance")
    parser.add_argument("--risk-model", type=Path, default=Path("config/risk_model.yaml"))
    parser.add_argument(
        "--history",
        type=Path,
        default=Path("public/data/history/risk/daily.json"),
        help="published risk history rows (dim_scores + total_score per day)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="artifact path (default: artifacts/risk/weight-audit-<YYYY-MM-DD>.json)",
    )
    args = parser.parse_args(argv)

    if not args.risk_model.exists():
        print(f"[risk-weight-audit] missing risk model config: {args.risk_model}", file=sys.stderr)
        return 2
    risk_model = _load_risk_model(args.risk_model)

    rows: list[dict] = []
    if args.history.exists():
        rows = _history_rows(_load_json(args.history))
    else:
        print(
            f"[risk-weight-audit] no risk history at {args.history}; "
            "reporting the static (config-only) audit",
            file=sys.stderr,
        )

    report = audit(risk_model, rows)
    report["artifact"] = "risk_weight_audit"
    report["artifact_version"] = "1.0.0"
    report["generated_at"] = date.today().isoformat()
    report["model_version"] = str(risk_model.get("model_version", "unknown"))
    report["history_source"] = str(args.history) if rows else None
    report["history_observations"] = len(rows)

    out = args.out or Path("artifacts") / "risk" / f"weight-audit-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(render(report))
    print(f"\n[risk-weight-audit] wrote {out}")

    blocking = blocking_findings(report)
    if blocking:
        print(
            "\n[risk-weight-audit] FAILED: configured indicator(s) have no scoring path — "
            "their weight is a constant in every published score.",
            file=sys.stderr,
        )
        for item in blocking:
            print(f"  {item['detail']}: {', '.join(item['evidence'])}", file=sys.stderr)
        return 1
    print("[risk-weight-audit] result: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
