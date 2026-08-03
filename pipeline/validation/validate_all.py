"""Full validation entry point (architecture §1.1/§3.5: reused by pipeline + CI).

For latest/*.json: schema validation (Pydantic) + schema_version compatibility + freshness annotation.
Any validation failure must not be published (three-artifact contract).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.schemas import (
    AnalysisDataset,
    CalendarEnvelope,
    CryptoEnvelope,
    DashboardEnvelope,
    EquitiesEnvelope,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import is_schema_compatible
from pipeline.validation.freshness import expected_interval_minutes_for, evaluate_freshness

# latest filename → (model, expected-interval dataset key)
DATASET_MODELS: dict[str, tuple[Any, str]] = {
    "macro.json": (MacroEnvelope, "macro"),
    "equities.json": (EquitiesEnvelope, "market"),
    "sectors.json": (SectorsEnvelope, "market"),
    "crypto.json": (CryptoEnvelope, "market"),
    "news.json": (NewsEnvelope, "news"),
    "calendar.json": (CalendarEnvelope, "calendar"),
    "risk.json": (RiskEnvelope, "analysis"),
    "dashboard.json": (DashboardEnvelope, "dashboard"),
}

# Self-describing contract files
STANDALONE_MODELS: dict[str, Any] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}


@dataclass
class ValidationReport:
    ok: bool = True
    files_checked: int = 0
    issues: list[str] = field(default_factory=list)

    def add_issue(self, issue: str) -> None:
        self.ok = False
        self.issues.append(issue)


def validate_file(path: Path) -> list[str]:
    """Validate a single data file, returning a list of issues (empty = pass)."""
    issues: list[str] = []
    name = path.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [f"{name}: unable to read JSON: {exc}"]

    if name in DATASET_MODELS:
        model, dataset_key = DATASET_MODELS[name]
        try:
            env = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            return [f"{name}: schema validation failed: {exc}"]
        if not is_schema_compatible(str(env.schema_version)):
            issues.append(f"{name}: schema_version {env.schema_version} incompatible")
        # freshness annotation (time dimension + enum validity)
        status = evaluate_freshness(env.generated_at, expected_interval_minutes_for(dataset_key, 480))
        if status == "stale":
            issues.append(f"{name}: data is stale (freshness=stale)")
    elif name in STANDALONE_MODELS:
        model = STANDALONE_MODELS[name]
        try:
            obj = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            return [f"{name}: schema validation failed: {exc}"]
        if not is_schema_compatible(str(getattr(obj, "schema_version", "1.0.0"))):
            issues.append(f"{name}: schema_version incompatible")
    else:
        issues.append(f"{name}: unknown dataset file (unregistered schema)")

    return issues


def validate_all(latest_dir: Path, strict: bool = True) -> ValidationReport:
    """Validate all known files under latest/. When strict=False, missing files are not treated as failures."""
    report = ValidationReport()
    known = {**DATASET_MODELS, **STANDALONE_MODELS}
    for name, _model in known.items():
        path = latest_dir / name
        if not path.exists():
            if strict:
                report.add_issue(f"{name}: file missing")
            continue
        report.files_checked += 1
        for issue in validate_file(path):
            report.add_issue(issue)
    return report


def main(latest_dir: str | None = None) -> int:
    from pipeline.settings import settings

    target = Path(latest_dir) if latest_dir else settings.data_dir / "latest"
    report = validate_all(target, strict=False)
    print(f"[validate_all] checked {report.files_checked} files, {len(report.issues)} issue(s)")
    for issue in report.issues:
        print(f"  - {issue}")
    return 0 if report.ok else 1
