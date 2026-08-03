"""运行报告（架构 §3.7 run_report.py → artifacts/logs）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_run_report(
    artifacts_dir: Path,
    *,
    command: str,
    ok: bool,
    durations: dict[str, float],
    provider_status: dict[str, Any],
    degraded: list[str],
    dataset_counts: dict[str, int],
    error: str | None = None,
) -> Path:
    """写 artifacts/logs/run-report-{ts}.json。"""
    logs_dir = artifacts_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "command": command,
        "ok": ok,
        "error": error,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "durations_seconds": {k: round(v, 3) for k, v in durations.items()},
        "provider_status": provider_status,
        "degraded": degraded,
        "dataset_counts": dataset_counts,
    }
    path = logs_dir / f"run-report-{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
