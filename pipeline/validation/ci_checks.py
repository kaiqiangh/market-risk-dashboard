"""T05 static data validation (shared by CI + local scripts; architecture §5#1 / PRD §20.2).

Covered checks (equivalent to validate-data.yml / scripts/validate_data.sh):
1. Schema validation: all JSON passes Pydantic isomorphic validation (no implicit fields/NaN/enum/time).
2. Required fields: latest/* known datasets + facts.json must exist; dashboard.json must pass when present.
3. Timestamps: envelope times are ISO 8601 UTC + Z (enforced by Pydantic UTCDateTime).
4. Data quality: data_quality ∈ [0,1] (Pydantic enforced + explicit re-check).
5. Risk score ranges: total_score / dimension.score / indicator.risk_score ∈ [0,100].
6. NaN/Infinity: illegal constants in JSON text (Python json.loads accepts them by default; rejected here).
7. Duplicate news: duplicate id / (title+source+published_at) in news.json.
8. Stale data: check generated_at against the expected frequency using the five-state freshness
   (stale is a WARNING, it does not block publishing — data is a static snapshot, and a code PR
   should not fail because of data timestamps).
9. Unknown language key: the language of analysis.*.json must be a supported language (zh-CN/en).
10. Bilingual missing: analysis.zh-CN.json and analysis.en.json must exist as a pair (error if one
    is missing); if both are missing, treat as AI degraded mode (WARNING).
11. AI bilingual conclusion mismatch: reuses pipeline/analysis/validate.compare_bilingual.

Exit code: 0 = pass (WARNING allowed); 1 = ERROR present.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.analysis.contract import SUPPORTED_LANGUAGES
from pipeline.analysis.validate import compare_bilingual
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
from pipeline.validation.freshness import evaluate_freshness

# latest filename → (model, expected-frequency dataset key); consistent with validate_all
ENVELOPE_MODELS: dict[str, tuple[Any, str]] = {
    "macro.json": (MacroEnvelope, "macro"),
    "equities.json": (EquitiesEnvelope, "market"),
    "sectors.json": (SectorsEnvelope, "market"),
    "crypto.json": (CryptoEnvelope, "market"),
    "news.json": (NewsEnvelope, "news"),
    "calendar.json": (CalendarEnvelope, "calendar"),
    "risk.json": (RiskEnvelope, "analysis"),
    "dashboard.json": (DashboardEnvelope, "dashboard"),
}

# Self-describing contract files (no envelope): must pass validation if present; presence not required.
# facts.json is produced on every pipeline run; analysis.*.json is produced by AI automation (missing = degraded mode).
STANDALONE_MODELS: dict[str, Any] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}

# Optional envelope files (must pass validation if present; presence not required)
OPTIONAL_ENVELOPE_MODELS: dict[str, tuple[Any, str]] = {}

# Time regex: ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ or with fractional seconds)
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FRESHNESS_ENUM = {"fresh", "delayed", "stale", "missing", "degraded"}


def _reject_constant(name: str) -> Any:
    """JSON parse_constant: reject NaN/Infinity/-Infinity (illegal per JSON spec)."""
    raise ValueError(f"JSON contains illegal constant: {name}")


@dataclass
class CheckReport:
    """Validation result: errors cause failure, warnings are informational only."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_checked: int = 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_json_strict(path: Path) -> dict[str, Any]:
    """Read JSON and reject NaN/Infinity constants (Python accepts them by default; rejected here explicitly)."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text, parse_constant=_reject_constant)


def check_latest(latest_dir: Path, report: CheckReport, now: datetime) -> None:
    """Validate all known files under latest/."""
    if not latest_dir.exists():
        report.error(f"latest directory missing: {latest_dir}")
        return

    known = {**ENVELOPE_MODELS, **OPTIONAL_ENVELOPE_MODELS}
    for name, model_spec in known.items():
        path = latest_dir / name
        if not path.exists():
            if name in OPTIONAL_ENVELOPE_MODELS:
                continue
            report.error(f"{name}: file missing (required dataset)")
            continue
        report.files_checked += 1
        _check_one(path, name, model_spec, report, now)

    # Self-describing contract files (validate if present; missing handled per semantics)
    for name, model in STANDALONE_MODELS.items():
        path = latest_dir / name
        if not path.exists():
            if name == "facts.json":
                report.error(f"{name}: file missing (must be produced on every pipeline run)")
            continue
        report.files_checked += 1
        _check_one(path, name, model, report, now)

    # Unknown analysis.*.json language (e.g. analysis.fr.json)
    for path in sorted(latest_dir.glob("analysis.*.json")):
        lang = path.name[len("analysis.") : -len(".json")]
        if lang not in SUPPORTED_LANGUAGES:
            report.error(f"{path.name}: unknown language key {lang!r} (supported: {SUPPORTED_LANGUAGES})")

    # Bilingual pair: if one exists, both must exist; both missing → AI degraded mode (WARNING)
    zh = latest_dir / "analysis.zh-CN.json"
    en = latest_dir / "analysis.en.json"
    if zh.exists() != en.exists():
        missing = "analysis.en.json" if not en.exists() else "analysis.zh-CN.json"
        report.error(f"missing bilingual analysis file: {missing} (must be published in pairs)")
    elif not zh.exists() and not en.exists():
        report.warn("analysis.*.json all missing: AI briefing not generated (degraded mode; site AI block shows degraded)")

    # Bilingual consistency (when both exist)
    if zh.exists() and en.exists():
        try:
            zh_obj = AnalysisDataset.model_validate(load_json_strict(zh))
            en_obj = AnalysisDataset.model_validate(load_json_strict(en))
            issues = compare_bilingual(zh_obj, en_obj)
            for issue in issues:
                report.error(f"AI bilingual conclusion mismatch: {issue}")
        except Exception as exc:  # noqa: BLE001
            report.error(f"AI bilingual validation failed: {exc}")


def _check_one(path: Path, name: str, model_spec: tuple[Any, str] | Any, report: CheckReport, now: datetime) -> None:
    """Validate a single file: schema + required + timestamp + data quality + risk range + staleness."""
    try:
        data = load_json_strict(path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        report.error(f"{name}: unable to read/parse JSON (contains NaN/Infinity?): {exc}")
        return

    if name in ENVELOPE_MODELS or name in OPTIONAL_ENVELOPE_MODELS:
        model, dataset_key = model_spec  # type: ignore[misc]
        try:
            env = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{name}: schema validation failed: {exc}")
            return
        # schema_version compatibility
        if not is_schema_compatible(str(env.schema_version)):
            report.error(f"{name}: schema_version {env.schema_version} incompatible")
        # Timestamp format (explicit re-check)
        for ts_field in ("generated_at", "source_updated_at"):
            value = getattr(env, ts_field, None)
            if value and not _ISO_UTC_RE.match(str(value)):
                report.error(f"{name}: {ts_field} is not ISO 8601 UTC: {value!r}")
        # Data quality
        if not (0.0 <= float(env.data_quality) <= 1.0):
            report.error(f"{name}: data_quality out of range [0,1]: {env.data_quality}")
        # freshness enum
        if env.freshness_status not in _FRESHNESS_ENUM:
            report.error(f"{name}: invalid freshness_status: {env.freshness_status}")
        # Stale data (time dimension; WARNING does not block)
        status = evaluate_freshness(str(env.generated_at), _expected_minutes(dataset_key), now)
        if status == "stale":
            report.warn(f"{name}: data is stale (freshness=stale, generated_at={env.generated_at})")
        elif status == "delayed":
            report.warn(f"{name}: data is delayed (freshness=delayed, generated_at={env.generated_at})")
        # Risk score ranges (explicit re-check for risk.json; payload may be a Pydantic model)
        if name == "risk.json":
            payload = env.payload
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump()
            _check_risk_ranges(payload, report, name)
    elif name in STANDALONE_MODELS:
        model = STANDALONE_MODELS[name]
        try:
            obj = model.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{name}: schema validation failed: {exc}")
            return
        if not is_schema_compatible(str(getattr(obj, "schema_version", "1.0.0"))):
            report.error(f"{name}: schema_version incompatible")
        if name.startswith("analysis."):
            if getattr(obj, "language", None) not in SUPPORTED_LANGUAGES:
                report.error(f"{name}: invalid language: {getattr(obj, 'language', None)!r}")


def _expected_minutes(dataset_key: str) -> int:
    """Expected update interval (minutes), read from config/sources.yaml, fallback 480 on failure."""
    try:
        from pipeline.settings import settings

        expectations = settings.load_sources().get("expectations", {})
        minutes = int(expectations.get(dataset_key, {}).get("interval_minutes", 480))
        return minutes if minutes > 0 else 480
    except Exception:  # noqa: BLE001
        return 480


def _check_risk_ranges(payload: dict[str, Any], report: CheckReport, name: str) -> None:
    """Explicit re-check of risk score ranges (Pydantic Field already constrains; double safety here)."""
    try:
        total = float(payload["total_score"])
        if not (0.0 <= total <= 100.0):
            report.error(f"{name}: total_score out of range [0,100]: {total}")
        for dim in payload.get("dimensions", []):
            score = float(dim.get("score", -1))
            if not (0.0 <= score <= 100.0):
                report.error(f"{name}: dimension {dim.get('key')} score out of range [0,100]: {score}")
            for ind in dim.get("indicators", []):
                rs = ind.get("risk_score")
                if rs is not None:
                    rs = float(rs)
                    if not (0.0 <= rs <= 100.0):
                        report.error(
                            f"{name}: indicator {ind.get('key')} risk_score out of range [0,100]: {rs}"
                        )
        confidence = payload.get("confidence")
        if confidence is not None and not (0.0 <= float(confidence) <= 1.0):
            report.error(f"{name}: confidence out of range [0,1]: {confidence}")
    except (KeyError, TypeError, ValueError) as exc:
        report.error(f"{name}: unable to re-check risk structure ranges: {exc}")


def check_news_duplicates(latest_dir: Path, report: CheckReport) -> None:
    """Duplicate news check: duplicate id / duplicate (title+source+published_at)."""
    path = latest_dir / "news.json"
    if not path.exists():
        return
    try:
        data = load_json_strict(path)
        items = data.get("payload", {}).get("items", [])
    except Exception as exc:  # noqa: BLE001
        report.error(f"news.json: unable to read for duplicate news check: {exc}")
        return
    ids: dict[str, int] = {}
    sigs: dict[str, int] = {}
    for i, item in enumerate(items):
        nid = item.get("id")
        if nid:
            ids[nid] = ids.get(nid, 0) + 1
        sig = (
            str(item.get("title", "")).strip().lower(),
            str(item.get("source", "")).strip().lower(),
            str(item.get("published_at", "")).strip(),
        )
        sigs[sig] = sigs.get(sig, 0) + 1
    for nid, count in ids.items():
        if count > 1:
            report.error(f"news.json: duplicate news id {nid!r} (appears {count} times)")
    for sig, count in sigs.items():
        if count > 1:
            report.error(f"news.json: duplicate news (title+source+published_at) {sig[0]!r} (appears {count} times)")


def check_history(data_dir: Path, report: CheckReport) -> None:
    """History slices: file parseable + row structure (date + total_score range)."""
    for series in ("risk", "market"):
        for slice_name in ("30d", "90d", "daily"):
            path = data_dir / "history" / series / f"{slice_name}.json"
            if not path.exists():
                report.warn(f"history/{series}/{slice_name}.json missing (should exist after warm-up backfill)")
                continue
            report.files_checked += 1
            try:
                rows = load_json_strict(path)
            except Exception as exc:  # noqa: BLE001
                report.error(f"history/{series}/{slice_name}.json: parse failed: {exc}")
                continue
            if not isinstance(rows, list):
                report.error(f"history/{series}/{slice_name}.json: top level should be an array")
                continue
            for row in rows:
                if not isinstance(row, dict):
                    report.error(f"history/{series}/{slice_name}.json: row is not an object")
                    continue
                date = row.get("date")
                if not _DATE_RE.match(str(date or "")):
                    report.error(f"history/{series}/{slice_name}.json: invalid row date: {date!r}")
                score = row.get("total_score")
                if score is not None:
                    try:
                        score = float(score)
                    except (TypeError, ValueError):
                        report.error(f"history/{series}/{slice_name}.json: invalid total_score: {score!r}")
                    else:
                        if not (0.0 <= score <= 100.0):
                            report.error(f"history/{series}/{slice_name}.json: total_score out of range [0,100]: {score}")
        index_path = data_dir / "history" / series / "index.json"
        if index_path.exists():
            report.files_checked += 1
            try:
                load_json_strict(index_path)
            except Exception as exc:  # noqa: BLE001
                report.error(f"history/{series}/index.json: parse failed: {exc}")


def check_metadata_and_feeds(data_dir: Path, report: CheckReport) -> None:
    """metadata/* and feeds/* parseable + basic structure."""
    meta_checks = {
        "metadata/freshness.json": ("datasets", "schema_version"),
        "metadata/sources.json": ("domains", "schema_version"),
        "metadata/schema-version.json": ("schema_version",),
        "feeds/fedwatch-history.json": (),
    }
    for rel, keys in meta_checks.items():
        path = data_dir / rel
        if not path.exists():
            report.warn(f"{rel} missing (system status page data source)")
            continue
        report.files_checked += 1
        try:
            data = load_json_strict(path)
        except Exception as exc:  # noqa: BLE001
            report.error(f"{rel}: parse failed: {exc}")
            continue
        for key in keys:
            if key not in data:
                report.warn(f"{rel}: missing field {key!r}")


def run_all(data_dir: Path, now: datetime | None = None) -> CheckReport:
    """Full validation entry point. data_dir points to public/data."""
    now = now or datetime.now(timezone.utc)
    report = CheckReport()
    latest = data_dir / "latest"
    check_latest(latest, report, now)
    check_news_duplicates(latest, report)
    check_history(data_dir, report)
    check_metadata_and_feeds(data_dir, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T05 static data validation (schema/required/timestamp/quality/risk range/NaN/duplicate/stale/language/bilingual)"
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="public/data directory (default: settings.data_dir)")
    args = parser.parse_args(argv)

    if args.data_dir is not None:
        data_dir = args.data_dir
    else:
        from pipeline.settings import settings

        data_dir = settings.data_dir

    report = run_all(data_dir)
    print(f"[validate_data] checked {report.files_checked} files, ERROR {len(report.errors)}, WARNING {len(report.warnings)}")
    for issue in report.errors:
        print(f"  [ERROR] {issue}")
    for issue in report.warnings:
        print(f"  [WARN ] {issue}")

    if not report.ok:
        print("[validate_data] result: failed (ERROR present)")
        return 1
    if report.warnings:
        print("[validate_data] result: passed (with WARNING, please review)")
    else:
        print("[validate_data] result: all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
