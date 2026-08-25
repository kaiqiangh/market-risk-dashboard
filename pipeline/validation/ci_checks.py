"""Canonical T05 static data validation (shared by pipeline, CI, and local scripts).

Covered checks (equivalent to validate-data.yml / scripts/validate_data.sh):
1. Schema validation: all JSON passes Pydantic isomorphic validation (no implicit fields/NaN/enum/time).
2. Required fields: latest/* known datasets + facts.json must exist; dashboard.json must pass when present.
3. Timestamps: envelope times are ISO 8601 UTC + Z (enforced by Pydantic UTCDateTime).
4. Data quality: data_quality ∈ [0,1] (Pydantic enforced + explicit re-check).
5. Risk score ranges: total_score / dimension.score / indicator.risk_score ∈ [0,100].
6. NaN/Infinity: illegal constants in JSON text (Python json.loads accepts them by default; rejected here).
7. Duplicate news: duplicate id / (title+source+published_at) in news.json.
8. Stale data: check generated_at against the expected frequency using the six-state freshness
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
from pipeline.analysis.validate import check_language_isolation, compare_bilingual
from pipeline.schemas import registry
from pipeline.schemas.envelope import FreshnessStatus, is_schema_compatible
from pipeline.validation.freshness import evaluate_freshness, expected_interval_minutes_for

# Views onto pipeline/schemas/registry.py. These used to be byte-identical copies of the tables
# in validate_all.py under a different name (D-3), which is how risk.json ended up mapped to the
# "analysis" interval here (720 min) and the "risk" interval in the envelope (480 min) — the same
# file could be fresh in its envelope and delayed in CI.
ENVELOPE_MODELS: dict[str, tuple[Any, str]] = {
    name: (spec.model, spec.key) for name, spec in registry.enveloped_specs().items()
}

# Self-describing contract files (no envelope): must pass validation if present; presence not required.
# facts.json is produced on every pipeline run; analysis.*.json is produced by AI automation (missing = degraded mode).
STANDALONE_MODELS: dict[str, Any] = {
    name: spec.model for name, spec in registry.standalone_specs().items()
}

# Time regex: ISO 8601 UTC (YYYY-MM-DDTHH:MM:SSZ or with fractional seconds)
_ISO_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Mirrors pipeline/analysis/validate._CJK_RE and the frontend CJK guard in displayLanguage.ts.
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
#: #225: below this coverage ratio the translation file is treated as a stale/mismatched batch
#: (a hard error); partial coverage between this and 100% is a warning.
_MIN_COVERAGE_RATIO = 0.5


def _normalize_title_key(text: str) -> str:
    """Punctuation/whitespace-insensitive title key (#225 translation coverage check)."""
    return re.sub(r"\W+", "", text or "").lower()


# Derived from the single definition in pipeline/schemas/envelope.py rather than restated (D-4).
_FRESHNESS_ENUM: frozenset[str] = frozenset(FreshnessStatus.__args__)  # type: ignore[attr-defined]


def _reject_constant(name: str) -> Any:
    """JSON parse_constant: reject NaN/Infinity/-Infinity (illegal per JSON spec)."""
    raise ValueError(f"JSON contains illegal constant: {name}")


@dataclass
class CheckReport:
    """Validation result: errors cause failure, warnings are informational only."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_checked: int = 0
    blocking_warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str, *, blocking: bool = False) -> None:
        self.warnings.append(msg)
        if blocking:
            self.blocking_warnings.append(msg)

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

    known = ENVELOPE_MODELS
    for name, model_spec in known.items():
        path = latest_dir / name
        if not path.exists():
            spec = registry.BY_FILENAME[name]
            # Requiredness is a registry invariant; only explicitly AI-owned optional files may
            # be absent.
            if not spec.required:
                continue
            report.error(f"{name}: file missing (required dataset)")
            continue
        report.files_checked += 1
        _check_one(path, name, model_spec, report, now)

    # Self-describing contract files (validate if present; missing handled per semantics)
    for name, model in STANDALONE_MODELS.items():
        path = latest_dir / name
        if not path.exists():
            if registry.BY_FILENAME[name].required:
                report.error(f"{name}: file missing (must be produced on every pipeline run)")
            continue
        report.files_checked += 1
        _check_one(path, name, model, report, now)

    # Unknown analysis.*.json language (e.g. analysis.fr.json)
    for path in sorted(latest_dir.glob("analysis.*.json")):
        lang = path.name[len("analysis.") : -len(".json")]
        if lang not in SUPPORTED_LANGUAGES:
            report.error(f"{path.name}: unknown language key {lang!r} (supported: {SUPPORTED_LANGUAGES})")

    # Refuse files under latest/ that are neither registered datasets nor build-time compressed
    # variants. Analysis language variants are handled above so their diagnostic remains specific.
    for path in sorted(latest_dir.iterdir()):
        if (
            path.is_file()
            and not registry.is_known_file(path.name)
            and not (path.name.startswith("analysis.") and path.name.endswith(".json"))
        ):
            report.error(f"{path.name}: unregistered file under latest/ (not validated)")

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
            analysis_model = registry.require("analysis").model
            zh_obj = analysis_model.model_validate(load_json_strict(zh))
            en_obj = analysis_model.model_validate(load_json_strict(en))
            issues = compare_bilingual(zh_obj, en_obj)
            for issue in issues:
                report.error(f"AI bilingual conclusion mismatch: {issue}")
            iso_issues = check_language_isolation(zh_obj, en_obj)
            for issue in iso_issues:
                report.error(f"AI bilingual {issue}")
        except Exception as exc:  # noqa: BLE001
            report.error(f"AI bilingual validation failed: {exc}")


def _check_one(path: Path, name: str, model_spec: tuple[Any, str] | Any, report: CheckReport, now: datetime) -> None:
    """Validate a single file: schema + required + timestamp + data quality + risk range + staleness."""
    try:
        data = load_json_strict(path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        report.error(f"{name}: unable to read/parse JSON (contains NaN/Infinity?): {exc}")
        return

    if name in ENVELOPE_MODELS:
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
        # E-2 re-assertion (#89/#101): `fresh` requires a non-empty payload. finalize_freshness
        # enforces this at assembly time; this re-checks the committed file so a hand-edited or
        # pre-#89 envelope cannot certify itself healthy again (the calendar published
        # `freshness_status: "fresh"` with `events: []` for weeks before this check existed).
        spec = registry.require(dataset_key)
        if env.freshness_status == "fresh" and spec.row_counted and spec.row_key is not None:
            rows = getattr(env.payload, spec.row_key, None)
            if rows is not None and len(rows) == 0:
                report.error(f"{name}: reports fresh but payload.{spec.row_key} is empty (E-2)")
        # Stale data (time dimension; WARNING does not block)
        status = evaluate_freshness(str(env.generated_at), _expected_minutes(dataset_key), now)
        if status == "stale":
            report.warn(
                f"{name}: data is stale (freshness=stale, generated_at={env.generated_at})",
                blocking=True,
            )
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


def validate_file(path: Path, now: datetime | None = None) -> list[str]:
    """Validate one registered data file through the canonical check implementation.

    This small public seam keeps the historical ``validate_all.validate_file`` API available
    for pipeline/storage callers without maintaining a second schema/freshness validator.
    """
    now = now or datetime.now(timezone.utc)
    report = CheckReport()
    name = path.name
    if name in ENVELOPE_MODELS:
        _check_one(path, name, ENVELOPE_MODELS[name], report, now)
    elif name in STANDALONE_MODELS:
        _check_one(path, name, STANDALONE_MODELS[name], report, now)
    else:
        report.error(f"{name}: unknown dataset file (unregistered schema)")
    # The historical one-file API treated stale data as a blocking issue but did not surface the
    # newer delayed warning. Keep that return contract while the structured report preserves both.
    return [*report.errors, *report.blocking_warnings]


def _expected_minutes(dataset_key: str) -> int:
    """Expected update interval (minutes) for a dataset.

    Delegates to the single reader in ``validation/freshness.py`` instead of reimplementing the
    config lookup — this was the third of three copies (D-2), and the only one that could
    disagree with the envelope about how fresh a file is.
    """
    return expected_interval_minutes_for(dataset_key, 480)


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


def check_news_language(latest_dir: Path, report: CheckReport) -> None:
    """Language isolation for news (architecture §3.4 / displayLanguage.safeDisplayText).

    ``news.json`` is the canonical store; the English UI reads ``title``/``summary`` directly, so
    those fields MUST be English. ``news.zh-translations.json`` carries the Chinese side
    (``title_zh``/``summary_zh``); if those lack Chinese the translation is suspicious.
    """
    path = latest_dir / "news.json"
    if not path.exists():
        return
    try:
        data = load_json_strict(path)
        items = data.get("payload", {}).get("items", [])
    except Exception as exc:  # noqa: BLE001
        report.error(f"news.json: unable to read for language check: {exc}")
        return
    for i, item in enumerate(items):
        for fname in ("title", "summary"):
            val = item.get(fname)
            if val and _CJK_RE.search(str(val)):
                report.error(
                    f"news.json item[{i}].{fname}: canonical English field contains Chinese "
                    f"(language isolation) — safeDisplayText will show 'Translation unavailable'"
                )
    zh_path = latest_dir / "news.zh-translations.json"
    if zh_path.exists():
        try:
            zdata = load_json_strict(zh_path)
            # The translations file may be envelope-wrapped (payload.items) or a bare item list.
            zitems = zdata.get("payload", {}).get("items", zdata.get("items", []))
        except Exception as exc:  # noqa: BLE001
            report.error(f"news.zh-translations.json: unable to read for language check: {exc}")
            return
        for i, item in enumerate(zitems):
            for fname in ("title_zh", "summary_zh"):
                val = item.get(fname)
                if val and not _CJK_RE.search(str(val)):
                    report.warn(
                        f"news.zh-translations.json item[{i}].{fname}: zh field contains no Chinese "
                        f"(suspicious — translation may be missing)"
                    )


def check_news_translation_coverage(latest_dir: Path, report: CheckReport) -> None:
    """The AI translation file must cover the current news batch (#225).

    ``merge_translations`` (ADR-0003) matches by id. When the external AI step emits a stale
    batch or re-derives ids, the merge silently no-ops and zh-source items keep Chinese
    canonical text (the "Translation unavailable" bug). This gate makes that failure visible at
    commit time: the translation file must cover ``news.json`` items by id or normalized title.
    """
    news_path = latest_dir / "news.json"
    zh_path = latest_dir / "news.zh-translations.json"
    if not news_path.exists() or not zh_path.exists():
        return
    try:
        news = load_json_strict(news_path)
        zdata = load_json_strict(zh_path)
    except Exception as exc:  # noqa: BLE001
        report.error(f"news translation coverage: unable to read news/translation files: {exc}")
        return
    n_items = news.get("payload", {}).get("items", [])
    z_items = zdata.get("payload", {}).get("items", zdata.get("items", []))
    if not n_items:
        return
    n_ids = {str(x.get("id", "")) for x in n_items if x.get("id")}
    z_ids = {str(x.get("id", "")) for x in z_items if x.get("id")}
    id_hits = len(n_ids & z_ids)
    z_title_keys = {_normalize_title_key(x.get("title_zh", "")) for x in z_items if x.get("title_zh")}
    content_hits = sum(
        1
        for x in n_items
        if _normalize_title_key(x.get("title", "")) in z_title_keys
        or _normalize_title_key(x.get("title_zh", "")) in z_title_keys
    )
    covered = max(id_hits, content_hits)
    total = len(n_ids)
    if covered < total:
        ratio = covered / total
        detail = (
            f"news.zh-translations.json covers only {covered}/{total} news items "
            f"(id overlap {id_hits}, title match {content_hits}); merge_translations will silently "
            f"no-op for the rest and zh-source items keep Chinese canonical text"
        )
        if ratio < _MIN_COVERAGE_RATIO:
            report.error(detail)
        else:
            report.warn(detail)


def _series_label(series_dir: Path, data_dir: Path) -> str:
    """Stable diagnostic label: path under history/, e.g. macro/BAA10Y (#191)."""
    return series_dir.relative_to(data_dir / "history").as_posix()

def _discover_series_dirs(data_dir: Path) -> list[Path]:
    """Every directory owning a daily.json is a series (#191).

    The tree nests (history/risk, history/macro/BAA10Y), so a single-level iterdir
   would mistake the intermediate macro/ for a series; anchoring on the daily.json
    leaf handles any depth without restating series names.
    """
    return sorted(
        (p.parent for p in (data_dir / "history").rglob("daily.json")), key=lambda p: str(p)
    )


def check_history(data_dir: Path, report: CheckReport) -> None:
    """History slices: file parseable + row structure (date + total_score range).

    The series list comes from the FILESYSTEM (#191): the old ("risk", "market")
    literals left history/macro/* (the durable ICE BofA archive) and any future
    series with zero validation coverage while pretending the gate was green.
    """
    history_root = data_dir / "history"
    if not history_root.exists():
        report.warn("history/: directory missing entirely (should exist after warm-up backfill)")
        return
    series_dirs = _discover_series_dirs(data_dir)
    for series_dir in series_dirs:
        series = _series_label(series_dir, data_dir)
        for slice_name in ("30d", "90d", "daily"):
            path = series_dir / f"{slice_name}.json"
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
        index_path = series_dir / "index.json"
        if index_path.exists():
            report.files_checked += 1
            try:
                load_json_strict(index_path)
            except Exception as exc:  # noqa: BLE001
                report.error(f"history/{series}/index.json: parse failed: {exc}")


def check_slice_consistency(data_dir: Path, report: CheckReport) -> None:
    """Pre-slices must equal the tail of their daily file, for EVERY series (#191).

    write_slices writes daily/30d/90d/index as separate atomic files - a crash between
    them can leave the group diverged (30d stale vs daily fresh), and nothing detected
    it. This check closes that gap, filesystem-driven so nested archives like
    history/macro/*/ are covered without restating series names.
    """
    history_root = data_dir / "history"
    if not history_root.exists():
        return
    for series_dir in _discover_series_dirs(data_dir):
        series = _series_label(series_dir, data_dir)
        daily_path = series_dir / "daily.json"
        if not daily_path.exists():
            continue  # absence itself is reported by check_history
        try:
            daily = load_json_strict(daily_path)
        except Exception as exc:  # noqa: BLE001 - already reported by check_history;
            continue  # a second error for the same file would just be noise
        if not isinstance(daily, list):
            continue
        for slice_name in ("30d", "90d"):
            slice_path = series_dir / f"{slice_name}.json"
            if not slice_path.exists():
                continue  # warm-up state; check_history warns on the miss
            try:
                sliced = load_json_strict(slice_path)
            except Exception:  # noqa: BLE001 - same single-report convention as above
                continue
            n = int(slice_name[:-1])
            expected = daily[-n:]
            if sliced != expected:
                report.error(
                    f"history/{series}/{slice_name}.json: diverged from daily.json tail"
                    f" ({len(sliced)} rows vs last {len(expected)}) - regenerate slices"
                )
        index_path = series_dir / "index.json"
        if index_path.exists():
            try:
                index_data = load_json_strict(index_path)
            except Exception:  # noqa: BLE001 - same single-report convention as above
                continue
            count = index_data.get("count") if isinstance(index_data, dict) else None
            if count is not None and not isinstance(count, int):
                report.error(f"history/{series}/index.json: count should be an integer, got {count!r}")
            elif isinstance(count, int) and count != len(daily):
                report.error(f"history/{series}/index.json: count {count} != {len(daily)} daily rows")


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


def _run_all(data_dir: Path, latest: Path, now: datetime) -> CheckReport:
    """Compose every Python validation category for one data tree."""
    report = CheckReport()
    check_latest(latest, report, now)
    check_news_duplicates(latest, report)
    check_news_language(latest, report)
    check_news_translation_coverage(latest, report)
    check_history(data_dir, report)
    check_slice_consistency(data_dir, report)
    check_metadata_and_feeds(data_dir, report)
    return report


def run_all(data_dir: Path, now: datetime | None = None) -> CheckReport:
    """Validate the complete ``public/data`` tree, including ``latest/``."""
    now = now or datetime.now(timezone.utc)
    return _run_all(data_dir, data_dir / "latest", now)


def run_latest(latest_dir: Path, now: datetime | None = None) -> CheckReport:
    """Validate a snapshot directory through the same composed authority as :func:`run_all`."""
    now = now or datetime.now(timezone.utc)
    return _run_all(latest_dir.parent, latest_dir, now)


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
