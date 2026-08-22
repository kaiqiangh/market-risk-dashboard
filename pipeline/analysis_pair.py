from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.report import write_run_report
from pipeline.schemas import registry as dataset_registry
from pipeline.schemas.envelope import FreshnessReason
from pipeline.settings import settings
from pipeline.storage import StorageWriter
from pipeline.storage.outcomes import RunOutcomes
from pipeline.validation.freshness import aggregate_freshness, finalize_freshness

#: Datasets whose content is AI-produced; their outcomes drive the AI pair gates (#192).
AI_PRODUCED_DATASETS: tuple[str, ...] = ("analysis", "news_translations")


def analysis_pair_paths(writer: StorageWriter) -> list[Path]:
    """Return the two published AI pair paths from the registry."""
    spec = dataset_registry.require("analysis")
    return [writer.latest_dir / name for name in spec.filenames]


def analysis_backup_paths(writer: StorageWriter) -> list[Path]:
    """Return the durable last-readable pair paths outside ``latest/``."""
    backup_dir = writer.history_dir / "analysis"
    return [
        backup_dir / f"last-good.{path.name.removeprefix('analysis.')}"
        for path in analysis_pair_paths(writer)
    ]


def read_analysis_pair(paths: list[Path]) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """Read both pair members without treating a partial pair as a valid document."""
    import json as _json

    absent = [path.name for path in paths if not path.exists()]
    if absent:
        return None, f"missing analysis pair member(s): {', '.join(absent)}"

    documents: dict[str, dict[str, Any]] = {}
    for path in paths:
        try:
            value = _json.loads(path.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            return None, f"unreadable analysis pair member: {path.name}"
        if not isinstance(value, dict):
            return None, f"analysis pair member is not an object: {path.name}"
        documents[path.name] = value
    return documents, None


def remove_analysis_pair(writer: StorageWriter) -> None:
    """Remove an invalid or partial candidate pair, never a durable backup."""
    for path in analysis_pair_paths(writer):
        path.unlink(missing_ok=True)


def snapshot_readable_analysis_pair(
    writer: StorageWriter, documents: dict[str, dict[str, Any]]
) -> None:
    """Persist a schema-valid bilingual pair for recovery from a later bad replacement."""
    for path in analysis_backup_paths(writer):
        source_name = f"analysis.{path.name.removeprefix('last-good.')}"
        writer.write_json(path, documents[source_name])


def restore_last_readable_analysis_pair(writer: StorageWriter) -> bool:
    """Restore the last schema-valid bilingual pair, if one exists."""
    documents, failure = read_analysis_pair(analysis_backup_paths(writer))
    if failure or documents is None:
        return False

    try:
        from pipeline.analysis.validate import compare_bilingual
        from pipeline.schemas import AnalysisDataset

        zh = AnalysisDataset.model_validate(documents["last-good.zh-CN.json"])
        en = AnalysisDataset.model_validate(documents["last-good.en.json"])
        if zh.language != "zh-CN" or en.language != "en" or compare_bilingual(zh, en):
            return False
    except Exception:  # noqa: BLE001 — an unusable backup must not replace the candidate
        return False

    latest_paths = analysis_pair_paths(writer)
    for latest_path in latest_paths:
        backup_name = f"last-good.{latest_path.name.removeprefix('analysis.')}"
        writer.write_json(latest_path, documents[backup_name])
    return True


def analysis_failure_reason(issues: list[str]) -> FreshnessReason:
    """Turn validation diagnostics into a closed, redacted freshness reason."""
    lineage = any(
        "lineage" in issue or "generation_id" in issue or "fact layer" in issue
        for issue in issues
    )
    if lineage:
        return FreshnessReason(
            code="input_dataset_unhealthy",
            detail="analysis lineage does not match the current fact layer; output not promoted",
        )
    return FreshnessReason(
        code="provider_parse_error",
        detail=f"analysis pair validation failed ({len(issues)} contract issue(s)); output not promoted",
    )


def record_analysis_outcome(writer: StorageWriter, outcomes: RunOutcomes) -> bool:
    """Validate, snapshot, and record the AI pair against the current fact layer.

    The return value means the pair is structurally valid and lineage-bound. A degraded or stale
    but valid pair can still be merged into the news dataset; its freshness outcome remains
    visible to the caller and the frontend.
    """
    import json as _json

    from pipeline.analysis.validate import validate_analysis_pair
    from pipeline.schemas import FactLayer

    paths = analysis_pair_paths(writer)
    documents, read_failure = read_analysis_pair(paths)
    if read_failure or documents is None:
        restored = restore_last_readable_analysis_pair(writer)
        if not restored:
            remove_analysis_pair(writer)
        outcomes.record(
            "analysis",
            "degraded",
            FreshnessReason(
                code="all_providers_failed" if "missing" in (read_failure or "") else "provider_parse_error",
                detail=(read_failure or "analysis pair unavailable")[:200],
            ),
            provider="ai_automation",
        )
        return False

    try:
        structural_issues, _, _ = validate_analysis_pair(paths[0], paths[1])
    except Exception:  # noqa: BLE001 — schema failure is an expected degraded AI outcome
        structural_issues = ["analysis pair schema validation failed"]
    if structural_issues:
        if not restore_last_readable_analysis_pair(writer):
            remove_analysis_pair(writer)
        outcomes.record(
            "analysis",
            "degraded",
            analysis_failure_reason(structural_issues),
            provider="ai_automation",
        )
        return False

    backup_documents, backup_failure = read_analysis_pair(analysis_backup_paths(writer))
    has_readable_backup = backup_documents is not None and backup_failure is None

    facts_path = writer.latest_dir / "facts.json"
    if not facts_path.exists():
        if has_readable_backup:
            restore_last_readable_analysis_pair(writer)
        else:
            snapshot_readable_analysis_pair(writer, documents)
        outcomes.record(
            "analysis",
            "degraded",
            FreshnessReason(
                code="input_dataset_unhealthy",
                detail="facts.json missing; analysis has no current basis",
            ),
            provider="ai_automation",
        )
        return False

    try:
        facts = FactLayer.model_validate(_json.loads(facts_path.read_text(encoding="utf-8")))
        issues, zh, en = validate_analysis_pair(paths[0], paths[1], facts_path, require_lineage=True)
    except Exception:  # noqa: BLE001 — malformed facts or AI output is a degraded outcome
        if has_readable_backup:
            restore_last_readable_analysis_pair(writer)
        else:
            snapshot_readable_analysis_pair(writer, documents)
        outcomes.record(
            "analysis",
            "degraded",
            FreshnessReason(
                code="input_dataset_unhealthy",
                detail="facts.json could not validate for analysis lineage",
            ),
            provider="ai_automation",
        )
        return False

    if issues:
        if has_readable_backup:
            restore_last_readable_analysis_pair(writer)
        else:
            snapshot_readable_analysis_pair(writer, documents)
        outcomes.record(
            "analysis",
            "degraded",
            analysis_failure_reason(issues),
            provider="ai_automation",
        )
        return False

    # Only a pair proven against the current fact layer may replace the durable recovery pair.
    snapshot_readable_analysis_pair(writer, documents)
    facts_status = aggregate_freshness(facts.data_freshness.values())
    oldest = min(str(zh.generated_at), str(en.generated_at))
    verdict = finalize_freshness("analysis", oldest, False)
    status = aggregate_freshness(
        [verdict.status, facts_status, str(zh.data_freshness), str(en.data_freshness)]
    )
    if status != verdict.status:
        culprits = sorted(
            k for k, value in facts.data_freshness.items() if str(value) == facts_status
        )
        reason = FreshnessReason(
            code="input_dataset_unhealthy",
            detail=f"analysis inputs are {facts_status}: {', '.join(culprits) or 'fact layer'}"[:200],
        )
    else:
        reason = verdict.reason
    outcomes.record("analysis", status, reason, provider="ai_automation")
    return True


def record_ai_outcomes(writer: StorageWriter, outcomes: RunOutcomes) -> bool:
    """Record the datasets the AI automations produce, from what is on disk (P0-4, §1.5).

    These are not collected by the pipeline, so their outcome is read back from the published
    files rather than observed during a fetch. Analysis is additionally bound to the current
    fact generation and restored from its last readable pair when a replacement is invalid.

    Recording rather than writing matters. Both files previously reached ``freshness.json``
    through their own read-modify-write, which is why ``news_translations`` never appeared in
    it at all — nothing ever called the writer for that key, and an absent entry is
    indistinguishable from a healthy one.
    """
    import json as _json

    analysis_valid = True

    for key in AI_PRODUCED_DATASETS:
        if key == "analysis":
            analysis_valid = record_analysis_outcome(writer, outcomes)
            continue
        spec = dataset_registry.require(key)
        paths = [writer.latest_dir / name for name in spec.filenames]
        absent = [p.name for p in paths if not p.exists()]
        if absent:
            outcomes.record(
                key,
                "degraded",
                FreshnessReason(
                    code="all_providers_failed",
                    detail=f"{', '.join(absent)} absent (no quota or retries exhausted)"[:200],
                ),
                provider="ai_automation",
            )
            continue

        # The pair is only as fresh as its *oldest* half: a Chinese brief regenerated against
        # yesterday's English one is not a fresh bilingual pair.
        timestamps: list[str] = []
        failure: str | None = None
        for path in paths:
            try:
                data = _json.loads(path.read_text(encoding="utf-8"))
            except (_json.JSONDecodeError, OSError) as exc:
                failure = f"{path.name} unreadable: {type(exc).__name__}"
                break
            stamp = data.get("generated_at") or data.get("updated_at") or ""
            timestamps.append(str(stamp))

        if failure is not None:
            outcomes.record(
                key,
                "degraded",
                FreshnessReason(code="provider_parse_error", detail=failure[:200]),
                provider="ai_automation",
            )
            continue

        oldest = min(timestamps) if timestamps and all(timestamps) else ""
        verdict = finalize_freshness(key, oldest or None, False)
        outcomes.record(key, verdict.status, verdict.reason, provider="ai_automation")

    return analysis_valid


def write_analysis_only_report(writer: StorageWriter, outcomes: RunOutcomes) -> None:
    """Write an operator-facing report for the no-collection analysis command.

    The metadata document remains the source of truth. The report repeats only closed reason
    codes and their bounded details, never fact contents or generation identifiers, so a
    degraded AI run is diagnosable without leaking the analysis input.
    """
    degraded_datasets: list[str] = []
    degraded_notes: list[str] = []
    for key in AI_PRODUCED_DATASETS:
        outcome = outcomes.get(key)
        if outcome is None or outcome.status not in {"degraded", "stale", "missing"}:
            continue
        degraded_datasets.append(key)
        degraded_notes.append(
            f"{key}: {outcome.reason.code} — {outcome.reason.detail}"[:240]
        )

    write_run_report(
        settings.artifacts_dir,
        command="analysis-only",
        ok=True,
        durations={},
        provider_status={},
        degraded=degraded_notes,
        dataset_counts={"latest": len(list(writer.latest_dir.glob("*.json")))},
        failed_datasets=[],
        skipped_datasets=[],
        degraded_datasets=degraded_datasets,
    )

