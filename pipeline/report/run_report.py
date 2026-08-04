"""Run report (architecture §3.7 run_report.py → artifacts/logs)."""

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
    failed_datasets: list[str] | None = None,
    skipped_datasets: list[str] | None = None,
    degraded_datasets: list[str] | None = None,
) -> Path:
    """Write artifacts/logs/run-report-{ts}.json.

    `failed_datasets` / `skipped_datasets` / `degraded_datasets` name the datasets whose
    outcome fell short of "published and current". `clean` is the single field an
    operator can read to tell a complete run from a partial one without opening a log:
    it is true only when the run succeeded and no dataset appears in any of those lists.

    `degraded` (free-text provider notes) also disqualifies a run. A note there without a
    corresponding entry in `degraded_datasets` still means something went wrong, and
    reporting the run as clean would be the lie this ticket exists to remove.
    """
    logs_dir = artifacts_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    failed = list(failed_datasets or [])
    skipped = list(skipped_datasets or [])
    degraded_names = list(degraded_datasets or [])
    clean = bool(ok) and not failed and not skipped and not degraded_names and not degraded
    report = {
        "command": command,
        "ok": ok,
        "clean": clean,
        "error": error,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "durations_seconds": {k: round(v, 3) for k, v in durations.items()},
        "provider_status": provider_status,
        "degraded": degraded,
        "failed_datasets": failed,
        "skipped_datasets": skipped,
        "degraded_datasets": degraded_names,
        "dataset_counts": dataset_counts,
    }
    path = logs_dir / f"run-report-{ts}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
