"""Pipeline CLI entry point (architecture §1.3 frozen command set + T03 full implementation + Fix rounds).

Commands:
  --full          Full (default): collect + indicators + risk + fact layer + storage
  --market-only   Quotes/crypto/A-shares only
  --macro-only    Macro only (FRED + FedWatch)
  --news-only     News only
  --analysis-only AI analysis file validation / Chinese translation merge only (no collection)
  --fact-layer    Rebuild fact layer only (no collection)
  --backfill      Warm-up backfill of 30-90 days of history (except FedWatch)
  --dry-run       Dry run without writing to disk
  --locale        Analysis language

Fix round additions/revisions:
- P0-4: when AI analysis is missing, metadata/freshness.json analysis domain = degraded (architecture §1.5)
- P1-5: --full produces latest/dashboard.json (homepage aggregation)
- P1-6: Chinese translation merge records to metadata/translations.json
- P1-7: unified freshness determination after writing (validation/freshness.finalize_freshness) before persisting
- P2-9: writer.read_history public method replaces private _read_json
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from pipeline import __version__
from pipeline.collectors import CalendarCollector, MacroCollector, MarketCollector, NewsCollector
from pipeline.factlayer import FactLayerBuilder
from pipeline.metadata import oldest_source_timestamp, row_count_for
from pipeline.providers import ProviderRegistry, build_registry
from pipeline.report import write_run_report
from pipeline.risk.model import RiskModel
from pipeline.schemas import (
    BaseEnvelope,
    CalendarEnvelope,
    CryptoEnvelope,
    DashboardAsset,
    DashboardEnvelope,
    DashboardPayload,
    EquitiesEnvelope,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas import registry as dataset_registry
from pipeline.schemas.envelope import (
    AssembledDataset,
    FreshnessReason,
    FreshnessStatus,
    assemble_dataset,
)
from pipeline.settings import settings
from pipeline.storage import StorageWriter
from pipeline.storage.outcomes import RunOutcomes
from pipeline.universe import AssetUniverse
from pipeline.utils import now_utc
from pipeline.validation.ci_checks import run_all as run_data_validation
from pipeline.validation.freshness import (
    FreshnessVerdict,
    aggregate_freshness,
    finalize_freshness,
)

COMMANDS = (
    "full",
    "market-only",
    "macro-only",
    "news-only",
    "analysis-only",
    "fact-layer",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.run", description="Market Risk Dashboard data pipeline CLI")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true", help="full (default): collect + indicators + risk + fact layer + storage")
    mode.add_argument("--market-only", action="store_true", help="quotes/crypto/A-shares only")
    mode.add_argument("--macro-only", action="store_true", help="macro only (FRED + FedWatch)")
    mode.add_argument("--news-only", action="store_true", help="news collection only")
    mode.add_argument("--analysis-only", action="store_true", help="AI analysis file validation/merge only (no collection)")
    mode.add_argument("--fact-layer", action="store_true", help="rebuild fact layer only (no collection)")
    parser.add_argument("--locale", choices=["zh-CN", "en"], default=None, help="analysis language (default bilingual)")
    parser.add_argument("--dry-run", action="store_true", help="dry run: validate config and arguments, no write to disk")
    parser.add_argument("--backfill", action="store_true", help="warm-up backfill of 30-90 days of history (except FedWatch)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_command(args: argparse.Namespace) -> str:
    for flag in COMMANDS:
        if getattr(args, flag.replace("-", "_")):
            return flag
    return "full"


# ============================================================
# Risk context assembly
# ============================================================

def _build_risk_context(
    macro: Any,
    equities: Any,
    crypto: Any,
    commodities: Any,
    histories: dict[str, list[dict[str, Any]]],
    qualities: list[float],
    prev_total_score: float | None,
    prev_dim_scores: dict[str, float] | None,
    risk_history: list[dict[str, Any]],
    series_history: dict[str, list[dict[str, Any]]],
    market_provenance: dict[str, Any] | None = None,
    macro_provenance: dict[str, Any] | None = None,
    crypto_provenance: dict[str, Any] | None = None,
    commodities_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the collected results into the context required by RiskModel.score."""
    from pipeline.indicators.breadth import breadth_snapshot
    from pipeline.indicators.trend import trend_snapshot

    breadth = breadth_snapshot(histories)
    trend = trend_snapshot(histories)

    # Cross-asset confirmation signals (#118). The first eight are the existing MVP
    # confirmation inputs. The two ETF relative-return signals are collected and published
    # as diagnostics (#143), but remain outside the production aggregate while the
    # calibration policy gates cross-asset refitting. Missing inputs are null, never benign.
    vix = _macro_value(macro, "volatility", "vixcls")
    hy = _macro_value(macro, "credit", "bamlh0a0hym2")
    dxy = _macro_value(macro, "fx", "dtwexbgs")
    real_rate = _macro_value(macro, "rates", "dfii10")
    spy_change = _latest_change(histories.get("SPY"))
    iwm_relative = breadth.get("small_cap_relative")
    btc_change = crypto.payload.assets[0].change_1d if crypto.payload.assets else None
    copper_change = _commodity_change(commodities, "HG=F")
    gold_change = _commodity_change(commodities, "GC=F")

    cyclicals_defensives = _relative_change(histories.get("XLY"), histories.get("XLP"))
    hy_treasury = _relative_change(histories.get("HYG"), histories.get("IEF"))

    signal_rows = [
        _cross_asset_signal("spy_down", spy_change, spy_change < 0 if spy_change is not None else None,
                            source="market_quotes", provider=market_provenance, unit="percentage_points",
                            transformation="one_day_return_below_zero", history=histories.get("SPY")),
        _cross_asset_signal("hy_oas_widening", hy, hy > 4.0 if hy is not None else None,
                            source="fred_macro", provider=macro_provenance, unit="index_points",
                            transformation="level_above_4", history=None),
        _cross_asset_signal("dollar_strength", dxy, dxy > 105 if dxy is not None else None,
                            source="fred_macro", provider=macro_provenance, unit="index_points",
                            transformation="level_above_105", history=None),
        _cross_asset_signal("real_rate_pressure", real_rate, real_rate > 1.5 if real_rate is not None else None,
                            source="fred_macro", provider=macro_provenance, unit="percentage_points",
                            transformation="level_above_1_5", history=None),
        _cross_asset_signal("bitcoin_down", btc_change, btc_change < 0 if btc_change is not None else None,
                            source="crypto_market", provider=crypto_provenance, unit="percentage_points",
                            transformation="one_day_return_below_zero", history=None),
        _cross_asset_signal("small_cap_underperformance", iwm_relative, iwm_relative < 0 if iwm_relative is not None else None,
                            source="market_quotes", provider=market_provenance, unit="percentage_points",
                            transformation="relative_return_below_zero", history=histories.get("IWM"), is_proxy=True),
        _cross_asset_signal("copper_down", copper_change, copper_change < 0 if copper_change is not None else None,
                            source="market_quotes", provider=commodities_provenance, unit="percentage_points",
                            transformation="one_day_return_below_zero", history=None),
        _cross_asset_signal("gold_up", gold_change, gold_change > 0 if gold_change is not None else None,
                            source="market_quotes", provider=commodities_provenance, unit="percentage_points",
                            transformation="one_day_return_above_zero", history=None),
        _cross_asset_signal("cyclicals_defensives_relative", cyclicals_defensives,
                            cyclicals_defensives < 0 if cyclicals_defensives is not None else None,
                            source="market_quotes", provider=market_provenance, unit="percentage_points",
                            transformation="xly_minus_xlp_one_day_return", history=histories.get("XLY"), is_proxy=True),
        _cross_asset_signal("hy_treasury_relative", hy_treasury,
                            hy_treasury < 0 if hy_treasury is not None else None,
                            source="market_quotes", provider=market_provenance, unit="percentage_points",
                            transformation="hyg_minus_ief_one_day_return", history=histories.get("HYG"), is_proxy=True),
    ]
    # The production aggregate intentionally excludes the two new signals while the
    # calibration policy is ``cross_asset_confirmation: gate``. Existing signals still use
    # null-aware aggregation so a failed provider cannot lower the hit rate artificially.
    production_signals = [row for row in signal_rows if row["key"] not in {
        "cyclicals_defensives_relative", "hy_treasury_relative",
    }]
    observed = [row["triggered"] for row in production_signals if row["triggered"] is not None]
    confirmation = round(sum(1 for value in observed if value) / len(observed), 4) if observed else None

    data_quality = sum(qualities) / len(qualities) if qualities else 1.0
    return {
        "macro": macro.payload,
        "equities": equities.payload,
        "crypto": crypto.payload,
        "commodities": commodities.payload,
        "histories": histories,
        "breadth": breadth,
        "trend": trend,
        # VIX is not one of the cross-asset hit-rate signals, but retain its canonical
        # volatility-group value in the shared context for downstream diagnostics/consumers.
        "cross_asset": {
            "confirmation": confirmation,
            "vix": vix,
            "signals": signal_rows,
            "configured_signal_count": len(signal_rows),
            "observed_signal_count": sum(row["triggered"] is not None for row in signal_rows),
            "production_scoring_signal_count": len(production_signals),
        },
        "data_quality": round(data_quality, 4),
        "series_history": series_history,
        "_prev_total_score": prev_total_score,
        "_prev_dim_scores": prev_dim_scores,
        "_risk_history": risk_history,
    }


def _commodity_change(commodities: Any, symbol: str) -> float | None:
    """1d change of a commodity asset by symbol (None when absent/failed)."""
    for asset in getattr(getattr(commodities, "payload", None), "assets", []) or []:
        if asset.symbol == symbol:
            return asset.change_1d
    return None


def _macro_value(macro: Any, group: str, key: str) -> float | None:
    for ind in getattr(macro.payload, group, []):
        if ind.key == key:
            return ind.value
    return None


def _latest_change(rows: list[dict[str, Any]]) -> float | None:
    if not rows or len(rows) < 2:
        return None
    prev, last = rows[-2].get("close"), rows[-1].get("close")
    if not all(isinstance(v, (int, float)) for v in (prev, last)) or prev == 0:
        return None
    return round((last - prev) / prev * 100.0, 4)


def _relative_change(left_rows: list[dict[str, Any]] | None, right_rows: list[dict[str, Any]] | None) -> float | None:
    """Return the 1d percentage-point return gap, preserving missing inputs as null."""
    left = _latest_change(left_rows or [])
    right = _latest_change(right_rows or [])
    if left is None or right is None:
        return None
    return round(left - right, 4)


def _signal_status(value: float | None, provenance: dict[str, Any] | None) -> str:
    if value is None:
        return "missing"
    if provenance and (provenance.get("degraded") or provenance.get("used_fallback") or provenance.get("from_cache")):
        return "degraded"
    return "fresh"


def _cross_asset_signal(
    key: str,
    value: float | None,
    triggered: bool | None,
    *,
    source: str,
    provider: dict[str, Any] | None,
    unit: str,
    transformation: str,
    history: list[dict[str, Any]] | None,
    is_proxy: bool = False,
) -> dict[str, Any]:
    """Build a serializable cross-asset signal row with input provenance."""
    return {
        "key": key,
        "value": value,
        "triggered": triggered,
        "source": source,
        "provider": str((provider or {}).get("provider", "unavailable")),
        "unit": unit,
        "transformation": transformation,
        "history_observations": len(history or []) if history is not None else (1 if value is not None else 0),
        "status": _signal_status(value, provider),
        "is_proxy": is_proxy,
        "production_scoring": key not in {"cyclicals_defensives_relative", "hy_treasury_relative"},
    }


def _read_prev_risk(writer: StorageWriter) -> tuple[float | None, dict[str, float] | None, list[dict[str, Any]]]:
    """Read risk history: previous day total score / previous day dimension scores / all prior rows (P2-9 public read_history)."""
    rows = writer.read_history("risk", "daily")
    if not rows:
        return None, None, []
    last = rows[-1]
    prev_total = last.get("total_score")
    prev_dims = last.get("dim_scores") if isinstance(last.get("dim_scores"), dict) else None
    if isinstance(prev_dims, dict):
        prev_dims = {str(k): float(v) for k, v in prev_dims.items() if isinstance(v, (int, float))}
    return prev_total, prev_dims, rows


# ============================================================
# Dataset health for the run report (#63)
# ============================================================

#: Every dataset a `--full` run is expected to publish, in canonical registry keys.
#:
#: Derived from the registry rather than listed by hand: a dataset added to the registry and
#: forgotten here would be collected, written, and then quietly excluded from the health
#: report. `analysis` and `news_translations` are `required=False` — the AI automations
#: produce them out of band, so a collection run that lacks them is degraded, not failed.
FULL_RUN_DATASETS: tuple[str, ...] = tuple(
    spec.key for spec in dataset_registry.DATASETS if spec.required
)

#: Datasets each command attempts. Anything in FULL_RUN_DATASETS and not listed here was
#: skipped by design — still worth naming, because a `--market-only` run leaves most of
#: the dashboard on yesterday's data and an operator should not have to infer that.
COMMAND_DATASETS: dict[str, tuple[str, ...]] = {
    "full": FULL_RUN_DATASETS,
    "market-only": ("equities", "sectors", "crypto", "commodities"),
    "macro-only": ("macro",),
    "news-only": ("news",),
    "fact-layer": ("factlayer",),
    "analysis-only": (),
}

#: Datasets the AI automations produce out of band, rather than the collection run (P0-4).
AI_PRODUCED_DATASETS: tuple[str, ...] = ("analysis", "news_translations")


def _run_scope(command: str) -> set[str]:
    """Datasets this command *observes* — a wider question than the one COMMAND_DATASETS answers.

    A ``--macro-only`` run does not produce the AI brief, but it does read it back and record
    what it found, so the brief is in scope: leaving it out would make the outcome record
    carry forward a stale entry the run had just disproved. The distinction cuts the other way
    too — a dataset in neither set keeps its previous entry rather than being reported
    ``missing`` by a run that never intended to touch it.
    """
    scope = set(COMMAND_DATASETS.get(command, FULL_RUN_DATASETS))
    if command in {"full", "macro-only", "fact-layer", "analysis-only"}:
        scope |= set(AI_PRODUCED_DATASETS)
    return scope

#: metadata/freshness.json status meaning the dataset produced nothing at all.
FAILED_FRESHNESS_STATUSES: frozenset[str] = frozenset({"missing"})

#: Statuses meaning the dataset published something we do not fully trust.
#: `delayed` is deliberately excluded: it is the ordinary state of a dataset whose
#: provider updates on a slower cadence than the run, and counting it would make
#: `clean` false on nearly every run, which would make the field useless.
DEGRADED_FRESHNESS_STATUSES: frozenset[str] = frozenset({"degraded", "stale"})


def dataset_health(writer: StorageWriter, command: str, *, run_started_at: str) -> dict[str, list[str]]:
    """Classify this run's datasets into failed / degraded / skipped.

    Reads the freshness metadata the run just wrote, which is already the system's
    record of per-dataset outcome, rather than threading a parallel tally through
    `_run_collection`. Datasets the command never attempted are reported as skipped.

    `run_started_at` is the wall-clock UTC instant (ISO 8601 + Z, same format as
    `now_utc`) at which this run began. It distinguishes "written during THIS run"
    from "written by a previous run": an entry whose freshness record predates the
    run start is a stale record, not evidence the dataset survived — a dataset that
    died before its freshness write must be loud, not masked by yesterday's `fresh`.
    """
    attempted = COMMAND_DATASETS.get(command, FULL_RUN_DATASETS)
    metadata = writer.read_freshness()

    failed: list[str] = []
    degraded: list[str] = []
    for name in attempted:
        entry = metadata.get(name)
        if not isinstance(entry, dict):
            # Attempted but no record written: the write did not complete.
            failed.append(name)
            continue
        # QA finding 1: an entry not written during this run is a previous run's record,
        # and must not mask a dataset that died before its freshness write. All freshness
        # timestamps come from `now_utc()` (ISO 8601 UTC, second precision, + Z suffix),
        # so lexicographic order is chronological order. An entry with no usable
        # timestamp cannot be proven current and is treated as stale as well.
        updated_at = str(entry.get("updated_at", ""))
        if updated_at < run_started_at:
            failed.append(name)
            continue
        status = str(entry.get("status", ""))
        if status in FAILED_FRESHNESS_STATUSES:
            failed.append(name)
        elif status in DEGRADED_FRESHNESS_STATUSES:
            degraded.append(name)

    skipped = [name for name in FULL_RUN_DATASETS if name not in attempted]
    return {"failed": failed, "degraded": degraded, "skipped": skipped}


# ============================================================
# Unified freshness write (P1-7 / #64 single freshness author)
# ============================================================

def _row_count(name: str, payload: Any) -> int | None:
    """How many rows a payload carries, or ``None`` when the question does not apply.

    Delegates to the one implementation in pipeline.metadata (#188): a second hand-copied
    version in scripts/backfill_metadata.py had diverged (0-vs-None for non-list payloads),
    which is exactly the drift this repo's single-source-of-truth rule exists to prevent.
    """
    return row_count_for(name, payload)


def _assemble(
    name: str,
    payload: Any,
    degraded: bool,
    *,
    provider: str,
    used_fallback: bool = False,
    from_cache: bool = False,
    data_quality: float,
    generated_at: str | None = None,
    source_updated_at: str | None = None,
    error_code: str | None = None,
    detail: str = "",
) -> AssembledDataset:
    """Build the envelope for `name` through the single assembly path (#64/#65).

    Freshness and its reason are computed by
    :func:`pipeline.schemas.envelope.assemble_dataset` via ``finalize_freshness`` — the only
    producer of either. `provider` is the resolved provider that actually served the dataset
    (#65): it becomes the envelope's source and provenance.

    Returns the envelope *and* its reason, because the caller has to record both into the run
    outcome that ``freshness.json`` and ``sources.json`` are rendered from.
    """
    return assemble_dataset(
        dataset_registry.require(name).model,
        payload,
        dataset=name,
        degraded=degraded,
        provider=provider,
        used_fallback=used_fallback,
        from_cache=from_cache,
        data_quality=data_quality,
        generated_at=generated_at,
        source_updated_at=source_updated_at,
        row_count=_row_count(name, payload),
        error_code=error_code,
        detail=detail,
    )


def _provider_kwargs(meta: dict[str, Any], dataset: str | None, default: str = "unavailable") -> dict[str, Any]:
    """Extract assemble_envelope provider kwargs from a collector meta (#65).

    ``dataset`` names the per-dataset outcome (market returns a ``providers`` dict); ``None``
    reads the single ``provider_outcome`` key (news/calendar).
    """
    outcome = None
    if dataset is not None:
        outcome = meta.get("providers", {}).get(dataset)
    else:
        outcome = meta.get("provider_outcome")
    if not isinstance(outcome, dict):
        outcome = {"provider": default, "used_fallback": False, "from_cache": False}
    return {
        "provider": str(outcome.get("provider", default)),
        "used_fallback": bool(outcome.get("used_fallback", False)),
        "from_cache": bool(outcome.get("from_cache", False)),
    }


def _write_finalized(
    writer: StorageWriter,
    name: str,
    assembled: AssembledDataset,
    outcomes: RunOutcomes,
) -> BaseEnvelope:
    """Persist an assembled dataset and record its outcome.

    Previously this both wrote the file and did a read-modify-write of ``freshness.json`` with
    a reason string produced right here — which is how eight datasets came to publish the
    literal word ``"degraded"`` as their diagnostic (E-1). The reason now arrives from the
    single freshness author, and the metadata file is rendered once, at the end of the run,
    from the complete outcome record.
    """
    writer.write_dataset(name, assembled.envelope)
    outcomes.record_envelope(name, assembled.envelope, assembled.reason)
    return assembled.envelope


def _finalize_and_write(
    writer: StorageWriter,
    name: str,
    payload: Any,
    degraded: bool,
    outcomes: RunOutcomes,
    *,
    provider: str,
    used_fallback: bool = False,
    from_cache: bool = False,
    data_quality: float,
    generated_at: str | None = None,
    source_updated_at: str | None = None,
    error_code: str | None = None,
    detail: str = "",
) -> BaseEnvelope:
    """Assemble through the single path, write, and record the outcome (#64/#65/#89).

    Collectors no longer fill freshness_status themselves; this recomputes the six-state
    status against the expected frequency from sources.yaml and records it, together with
    its structured reason, into the run's outcome record. The metadata files are rendered
    from that record once, at the end of the run. The resolved provider (and whether it was
    a fallback / cache replay) is published as source + provenance (#65).

    ``extra_reason`` used to exist here as a free-text string appended by the caller. It is
    gone: reasons are now authored in one place, from a closed vocabulary.
    """
    assembled = _assemble(name, payload, degraded, provider=provider,
                          used_fallback=used_fallback, from_cache=from_cache,
                          data_quality=data_quality, generated_at=generated_at,
                          source_updated_at=source_updated_at,
                          error_code=error_code, detail=detail)
    return _write_finalized(writer, name, assembled, outcomes)


def _aggregate_outcome(
    own: FreshnessVerdict,
    inputs: dict[str, Any],
) -> tuple[FreshnessStatus, FreshnessReason]:
    """Combine a derived dataset's own verdict with the freshness of its inputs.

    A derived dataset (the fact layer, the dashboard) is only as trustworthy as its worst
    input. When an input drags the status down, the reason has to say so: reporting
    ``stale`` with reason ``ok`` — which the previous free-text reason effectively did by
    writing the status back as its own explanation — tells the operator nothing about which
    dataset to go and fix.
    """
    worst_status = aggregate_freshness([own.status, *(str(v) for v in inputs.values())])
    if worst_status == own.status:
        return own.status, own.reason
    culprits = sorted(k for k, v in inputs.items() if str(v) == worst_status)
    return worst_status, FreshnessReason(
        code="input_dataset_unhealthy",
        detail=f"aggregated from inputs; {worst_status}: {', '.join(culprits) or 'unknown'}"[:200],
    )


def _analysis_pair_paths(writer: StorageWriter) -> list[Path]:
    """Return the two published AI pair paths from the registry."""
    spec = dataset_registry.require("analysis")
    return [writer.latest_dir / name for name in spec.filenames]


def _analysis_backup_paths(writer: StorageWriter) -> list[Path]:
    """Return the durable last-readable pair paths outside ``latest/``."""
    backup_dir = writer.history_dir / "analysis"
    return [
        backup_dir / f"last-good.{path.name.removeprefix('analysis.')}"
        for path in _analysis_pair_paths(writer)
    ]


def _read_analysis_pair(paths: list[Path]) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
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


def _remove_analysis_pair(writer: StorageWriter) -> None:
    """Remove an invalid or partial candidate pair, never a durable backup."""
    for path in _analysis_pair_paths(writer):
        path.unlink(missing_ok=True)


def _snapshot_readable_analysis_pair(
    writer: StorageWriter, documents: dict[str, dict[str, Any]]
) -> None:
    """Persist a schema-valid bilingual pair for recovery from a later bad replacement."""
    for path in _analysis_backup_paths(writer):
        source_name = f"analysis.{path.name.removeprefix('last-good.')}"
        writer.write_json(path, documents[source_name])


def _restore_last_readable_analysis_pair(writer: StorageWriter) -> bool:
    """Restore the last schema-valid bilingual pair, if one exists."""
    documents, failure = _read_analysis_pair(_analysis_backup_paths(writer))
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

    latest_paths = _analysis_pair_paths(writer)
    for latest_path in latest_paths:
        backup_name = f"last-good.{latest_path.name.removeprefix('analysis.')}"
        writer.write_json(latest_path, documents[backup_name])
    return True


def _analysis_failure_reason(issues: list[str]) -> FreshnessReason:
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


def _record_analysis_outcome(writer: StorageWriter, outcomes: RunOutcomes) -> bool:
    """Validate, snapshot, and record the AI pair against the current fact layer.

    The return value means the pair is structurally valid and lineage-bound. A degraded or stale
    but valid pair can still be merged into the news dataset; its freshness outcome remains
    visible to the caller and the frontend.
    """
    import json as _json

    from pipeline.analysis.validate import validate_analysis_pair
    from pipeline.schemas import FactLayer

    paths = _analysis_pair_paths(writer)
    documents, read_failure = _read_analysis_pair(paths)
    if read_failure or documents is None:
        restored = _restore_last_readable_analysis_pair(writer)
        if not restored:
            _remove_analysis_pair(writer)
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
        if not _restore_last_readable_analysis_pair(writer):
            _remove_analysis_pair(writer)
        outcomes.record(
            "analysis",
            "degraded",
            _analysis_failure_reason(structural_issues),
            provider="ai_automation",
        )
        return False

    backup_documents, backup_failure = _read_analysis_pair(_analysis_backup_paths(writer))
    has_readable_backup = backup_documents is not None and backup_failure is None

    facts_path = writer.latest_dir / "facts.json"
    if not facts_path.exists():
        if has_readable_backup:
            _restore_last_readable_analysis_pair(writer)
        else:
            _snapshot_readable_analysis_pair(writer, documents)
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
            _restore_last_readable_analysis_pair(writer)
        else:
            _snapshot_readable_analysis_pair(writer, documents)
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
            _restore_last_readable_analysis_pair(writer)
        else:
            _snapshot_readable_analysis_pair(writer, documents)
        outcomes.record(
            "analysis",
            "degraded",
            _analysis_failure_reason(issues),
            provider="ai_automation",
        )
        return False

    # Only a pair proven against the current fact layer may replace the durable recovery pair.
    _snapshot_readable_analysis_pair(writer, documents)
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


def _record_ai_outcomes(writer: StorageWriter, outcomes: RunOutcomes) -> bool:
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
            analysis_valid = _record_analysis_outcome(writer, outcomes)
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


def _write_analysis_only_report(writer: StorageWriter, outcomes: RunOutcomes) -> None:
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


def _publish_metadata(
    writer: StorageWriter,
    outcomes: RunOutcomes,
    provider_status: dict[str, Any] | None = None,
) -> None:
    """Render both metadata files from the one outcome record (#89).

    Writing them together, from the same source, is the mechanism that makes the old
    contradiction unrepresentable: ``sources.json`` cannot call a domain healthy while
    ``freshness.json`` calls its dataset degraded, because ``degraded`` in both files is
    *derived* from the same outcomes — and, on partial runs, both carry forward out-of-scope
    state together so a ``--news-only`` run cannot reset a previously-degraded domain.

    ``provider_status`` is omitted by commands that fetch nothing (``--fact-layer``,
    ``--analysis-only``); rewriting provider health from a run that contacted no provider
    would replace real information with an empty guess.
    """
    writer.write_freshness_metadata(outcomes.freshness_projection(writer.read_freshness_raw()))
    if provider_status is not None:
        writer.write_sources_metadata(
            outcomes.sources_projection(provider_status, writer.read_sources_raw())
        )


# ============================================================
# Homepage aggregation (P1-5)
# ============================================================

def _build_dashboard(
    risk_env: RiskEnvelope,
    equities: Any,
    crypto: Any,
    sectors: Any,
    calendar: Any,
) -> DashboardPayload:
    """Aggregate key fields from risk/crypto/equities/sectors/calendar (architecture §2 L299 + §3.6).

    Returns the payload only (#64 follow-up): the envelope's schema_version / source /
    source_updated_at / freshness_status / data_quality are supplied by the caller through
    the single assembly path — the values a hand-built envelope carries are discarded by
    ``_finalize_and_write`` and were a latent trap.
    """
    r = risk_env.payload

    cross_asset: list[DashboardAsset] = []
    for a in equities.payload.assets[:6]:
        cross_asset.append(DashboardAsset(asset=a.symbol, category="equity", change_1d=a.change_1d))
    for a in crypto.payload.assets[:3]:
        cross_asset.append(DashboardAsset(asset=a.symbol, category="crypto", change_1d=a.change_1d))

    catalysts = [e.model_dump() for e in calendar.payload.events[:5]]

    sector_performance: list[dict[str, Any]] = []
    if sectors is not None:
        # #102 (C-1): no labels here — the payload carries key + change; the frontend renders
        # t(themes.<key>) from i18n, so dashboard.json has nothing to display-label.
        for s in sectors.payload.sectors:
            sector_performance.append({"key": s.key, "change_1d": s.change_1d})
        for t in sectors.payload.themes:
            sector_performance.append({"key": t.key, "change_1d": t.change_1d})

    return DashboardPayload(
        risk=r,
        regime=r.regime,
        top_drivers=r.top_drivers,
        cross_asset=cross_asset,
        catalysts=catalysts,
        sector_performance=sector_performance,
    )


# ============================================================
# Commands
# ============================================================

def _empty_results() -> dict[str, Any]:
    """The one initializer for a collection-result bundle (#187).

    Both `_run_collection` and `main()`'s crash-handler skeleton start from this factory:
    two hand-copied literals asserting one shape is exactly the drift class this repo keeps
    getting burned by — a key added by a collector would otherwise vanish from the next
    early-crash failure report.
    """
    return {
        "durations": {},
        "degraded": [],
        "provider_status": {},
        "histories": {},
        "qualities": [],
        "prev_total_score": None,
        "prev_dim_scores": None,
        "risk_history": [],
        "series_history": {},
        "macro_meta": {},
    }


def _run_collection(command: str) -> dict[str, Any]:
    """Run collection according to the command, returning collected results and durations."""
    started = time.monotonic()
    registry = build_registry(settings)
    universe = AssetUniverse.load(settings)
    writer = StorageWriter(settings.data_dir)

    results = _empty_results()

    need_market = command in ("full", "market-only")
    need_macro = command in ("full", "macro-only")
    need_news = command in ("full", "news-only")
    need_calendar = command in ("full",)

    if need_market:
        t0 = time.monotonic()
        mc = MarketCollector(registry, universe, settings)
        market = mc.collect()
        results.update(
            equities=market["equities"],
            crypto=market["crypto"],
            commodities=market["commodities"],
            sectors=market["sectors"],
            histories=market["histories"],
        )
        results["market_meta"] = market
        results["degraded"].extend(market["degraded"])
        results["provider_status"].update(market["provider_status"])
        results["qualities"].append(market.get("risk_data_quality", market["data_quality"]))
        results["durations"]["market"] = time.monotonic() - t0

    if need_macro:
        t0 = time.monotonic()
        macc = MacroCollector(registry, settings)
        macro, macro_meta = macc.collect()
        results["macro"] = macro
        results["macro_meta"] = macro_meta
        results["degraded"].extend(macro_meta["degraded"])
        results["provider_status"].update(macro_meta["provider_status"])
        results["series_history"] = macro_meta.get("series_history", {})
        # #96 (shape per #84 §3): per-series append-only archive + per-group 30d/90d UI
        # bundles + manifest. Only when there is history to persist.
        if results["series_history"]:
            from pipeline.collectors.macro import SERIES_GROUPS
            from pipeline.storage.macro_history import write_macro_history

            write_macro_history(writer, results["series_history"], SERIES_GROUPS)
        results["qualities"].append(macro_meta["data_quality"])
        results["durations"]["macro"] = time.monotonic() - t0

    if need_calendar:
        t0 = time.monotonic()
        ccc = CalendarCollector(registry, settings)
        calendar, cal_meta = ccc.collect()
        results["calendar"] = calendar
        results["calendar_meta"] = cal_meta
        results["calendar_degraded"] = bool(cal_meta["degraded"])
        results["degraded"].extend(cal_meta["degraded"])
        results["provider_status"].update(cal_meta["provider_status"])
        results["durations"]["calendar"] = time.monotonic() - t0

    if need_news:
        t0 = time.monotonic()
        ncc = NewsCollector(registry, settings)
        news, news_meta = ncc.collect()
        # Merge AI Chinese translations (if present) + record merge status (P1-6)
        merged = _merge_news_translations(writer, ncc, news, settings.data_dir / "latest" / "news.zh-translations.json")
        if merged is not None:
            news = merged
        results["news"] = news
        results["news_meta"] = news_meta
        results["news_degraded"] = bool(news_meta["degraded"])
        results["degraded"].extend(news_meta["degraded"])
        results["provider_status"]["news"] = {
            "provider": news_meta.get("provider", "rss_news"),
            "sources": news_meta.get("source_status", {}),
        }
        results["durations"]["news"] = time.monotonic() - t0

    results["durations"]["collection"] = time.monotonic() - started
    return results


def _run_risk_and_write(results: dict[str, Any], writer: StorageWriter, command: str) -> tuple[bool, str | None]:
    """Compute risk + fact layer + dashboard + write + unified freshness + validate. Returns (ok, error)."""
    market_meta = results.get("market_meta", {})
    macro_meta = results.get("macro_meta", {})
    news_meta = results.get("news_meta", {})
    calendar_meta = results.get("calendar_meta", {})
    # #119: degradation is PER-DATASET, not a single global flag. The old code passed
    # `bool(results["degraded"])` — a list extended by market + macro + calendar + news
    # collectors — to every market envelope, so an RSS outage degraded equities/sectors/
    # crypto/commodities that had collected fine. Each dataset now carries only its own
    # collector's degradation; derived datasets (risk, dashboard) aggregate from the inputs
    # they actually consume.
    market_degraded = bool(market_meta.get("degraded"))
    market_degraded_by_dataset = market_meta.get("degraded_by_dataset", {})
    macro_degraded = bool(macro_meta.get("degraded"))
    news_degraded = bool(results.get("news_degraded", False))
    calendar_degraded = bool(results.get("calendar_degraded", False))
    risk_history_degraded = bool(market_meta.get("risk_history_degraded", False))
    # risk consumes macro + market only (breadth/trend/cross-asset); news/calendar do not
    # feed it, so their degradation must not drag the risk score down.
    risk_market_degraded = any(
        bool(market_degraded_by_dataset.get(name, market_degraded))
        for name in ("equities", "crypto", "commodities")
    )
    risk_input_degraded = risk_market_degraded or macro_degraded or risk_history_degraded
    try:
        # #64/#65: assemble every envelope through the single path (freshness = finalize_freshness;
        # source + provenance = the resolved provider from the collector's outcome).
        macro_outcome = macro_meta.get("provider", {"provider": "unavailable", "used_fallback": False, "from_cache": False})
        market_quality = market_meta.get("data_quality_by_dataset", {})
        market_source = market_meta.get("source_updated_at_by_dataset", {})
        macro = _assemble("macro", results["macro"], macro_degraded,
                          provider=str(macro_outcome.get("provider", "unavailable")),
                          used_fallback=bool(macro_outcome.get("used_fallback", False)),
                          from_cache=bool(macro_outcome.get("from_cache", False)),
                          data_quality=macro_meta.get("data_quality", 1.0),
                          source_updated_at=macro_meta.get("source_updated_at"))
        equities = _assemble("equities", results["equities"], bool(market_degraded_by_dataset.get("equities", market_degraded)),
                             **_provider_kwargs(market_meta, "equities"),
                             data_quality=market_quality.get("equities", market_meta.get("data_quality", 1.0)),
                             source_updated_at=market_source.get("equities"))
        sectors = _assemble("sectors", results["sectors"], bool(market_degraded_by_dataset.get("sectors", market_degraded)),
                            **_provider_kwargs(market_meta, "sectors"),
                            data_quality=market_quality.get("sectors", market_meta.get("data_quality", 1.0)),
                            source_updated_at=market_source.get("sectors"),
                            detail=market_meta.get("degraded_detail_by_dataset", {}).get("sectors", ""))
        crypto = _assemble("crypto", results["crypto"], bool(market_degraded_by_dataset.get("crypto", market_degraded)),
                           **_provider_kwargs(market_meta, "crypto"),
                           data_quality=market_quality.get("crypto", market_meta.get("data_quality", 1.0)),
                           source_updated_at=market_source.get("crypto"))
        commodities = _assemble("commodities", results["commodities"], bool(market_degraded_by_dataset.get("commodities", market_degraded)),
                                **_provider_kwargs(market_meta, "commodities"),
                                data_quality=market_quality.get("commodities", market_meta.get("data_quality", 1.0)),
                                source_updated_at=market_source.get("commodities"))
        news = _assemble("news", results["news"], news_degraded,
                         **_provider_kwargs(news_meta, None, default="rss_news"),
                         data_quality=news_meta.get("data_quality", 1.0),
                         source_updated_at=news_meta.get("source_updated_at"))
        calendar = _assemble("calendar", results["calendar"], calendar_degraded,
                             **_provider_kwargs(calendar_meta, None, default="fmp"),
                             data_quality=calendar_meta.get("data_quality", 1.0),
                             source_updated_at=calendar_meta.get("source_updated_at"))

        risk_model = RiskModel(settings)
        prev_score, prev_dims, risk_history = _read_prev_risk(writer)
        # #99 (verified end to end): _assemble returns AssembledDataset (the #101 single
        # assembly path); the risk context and the fact layer operate on ENVELOPES.
        ctx = _build_risk_context(
            macro=macro.envelope,
            equities=equities.envelope,
            crypto=crypto.envelope,
            commodities=commodities.envelope,
            histories=results.get("histories", {}),
            qualities=results["qualities"],
            prev_total_score=prev_score,
            prev_dim_scores=prev_dims,
            risk_history=risk_history,
            series_history=results.get("series_history", {}),
            market_provenance=market_meta.get("providers", {}).get("equities"),
            macro_provenance=macro_outcome,
            crypto_provenance=market_meta.get("providers", {}).get("crypto"),
            commodities_provenance=market_meta.get("providers", {}).get("commodities"),
        )
        risk_result = risk_model.score(ctx)
        risk_source_updated_at = oldest_source_timestamp(
            [
                macro.envelope.source_updated_at,
                equities.envelope.source_updated_at,
                crypto.envelope.source_updated_at,
                commodities.envelope.source_updated_at,
            ]
        )
        risk_env = _assemble("risk", risk_result, risk_input_degraded,
                             provider="risk_model",
                             data_quality=ctx["data_quality"],
                             source_updated_at=risk_source_updated_at)

        builder = FactLayerBuilder()
        facts = builder.build(
            risk=risk_env.envelope,
            macro=macro.envelope,
            equities=equities.envelope,
            crypto=crypto.envelope,
            news=news.envelope,
            calendar=calendar.envelope,
            sectors=sectors.envelope if sectors is not None else None,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"risk/fact layer computation failed: {exc}"

    # ---- Write (persist after unified freshness determination, P1-7) ----
    outcomes = RunOutcomes(scope=_run_scope(command))
    try:
        macro = _write_finalized(writer, "macro", macro, outcomes)
        equities = _write_finalized(writer, "equities", equities, outcomes)
        sectors = _write_finalized(writer, "sectors", sectors, outcomes)
        crypto = _write_finalized(writer, "crypto", crypto, outcomes)
        commodities = _write_finalized(writer, "commodities", commodities, outcomes)
        news = _write_finalized(writer, "news", news, outcomes)
        calendar = _write_finalized(writer, "calendar", calendar, outcomes)
        risk_env = _write_finalized(writer, "risk", risk_env, outcomes)

        writer.write_standalone("facts", facts.model_dump(mode="json"))
        # The fact layer is an aggregation, so its status is the worst of its inputs rather
        # than a wall-clock comparison against its own timestamp — the same rule the rebuild
        # path uses, so `--full` and `--fact-layer` cannot disagree about the same facts.
        # Its own degraded flag must reflect EVERY input it consumes (market + macro + news +
        # calendar) — the old single global flag made an RSS outage degrade the market too,
        # and a market/macro-only flag would silently under-report a news outage on rebuild.
        factlayer_input_degraded = (
            risk_input_degraded
            or bool(market_degraded_by_dataset.get("sectors", market_degraded))
            or news_degraded
            or calendar_degraded
        )
        # #125: the aggregate's own reason must be `input_dataset_unhealthy` (closed
        # vocabulary, envelope.py) naming its culprits — NOT the worst input's own code
        # (e.g. news `provider_http_error`), which would falsely imply the fact layer hit
        # a provider error. Mirrors the fact-layer rebuild path: culprits = the inputs at
        # the aggregated worst status, so a merely stale dataset is not blamed for a
        # degraded fact layer.
        facts_status = aggregate_freshness(facts.data_freshness.values())
        culprits = sorted(k for k, v in facts.data_freshness.items() if str(v) == facts_status and facts_status != "fresh")
        facts_verdict = finalize_freshness(
            "factlayer", str(risk_env.generated_at), factlayer_input_degraded,
            row_count=len(facts.data_freshness) or None,
            error_code="input_dataset_unhealthy" if factlayer_input_degraded else None,
            detail=f"aggregated from inputs; {facts_status}: {', '.join(culprits) or 'unknown'}"[:200]
            if factlayer_input_degraded else "",
        )
        status, reason = _aggregate_outcome(facts_verdict, facts.data_freshness)
        outcomes.record("factlayer", status, reason, provider="fact_layer")

        # dashboard (P1-5) — renders risk + calendar + market content, not news: its degraded
        # flag follows risk's inputs plus the calendar, NOT the global aggregate (#119).
        dashboard_market_degraded = any(
            bool(market_degraded_by_dataset.get(name, market_degraded))
            for name in ("equities", "crypto", "sectors")
        )
        dashboard_degraded = risk_input_degraded or dashboard_market_degraded or calendar_degraded
        dashboard_payload = _build_dashboard(
            risk_env=risk_env,
            equities=equities,
            crypto=crypto,
            sectors=sectors,
            calendar=calendar,
        )
        # #174: the dashboard never contacts a provider, so its degraded reason must be
        # `input_dataset_unhealthy` naming the culprits at the aggregated worst status — NOT
        # the default `provider_http_error`, which would falsely imply the dashboard itself
        # hit a provider. Mirrors the fact-layer pattern (#125): aggregate over the
        # dashboard's own inputs (risk + the market content it renders + calendar).
        dashboard_inputs = {
            "risk": risk_env.freshness_status,
            "equities": equities.freshness_status,
            "crypto": crypto.freshness_status,
            "sectors": sectors.freshness_status if sectors is not None else "missing",
            "calendar": calendar.freshness_status,
        }
        dashboard_status = aggregate_freshness(dashboard_inputs.values())
        dashboard_culprits = sorted(
            k for k, v in dashboard_inputs.items()
            if str(v) == dashboard_status and dashboard_status != "fresh"
        )
        dashboard_env = _finalize_and_write(
            writer, "dashboard", dashboard_payload, dashboard_degraded, outcomes,
            provider="risk_model",
            data_quality=round(ctx["data_quality"], 3),
            source_updated_at=oldest_source_timestamp(
                [
                    risk_env.source_updated_at,
                    equities.source_updated_at,
                    crypto.source_updated_at,
                    sectors.source_updated_at if sectors is not None else None,
                    calendar.source_updated_at,
                ]
            ),
            error_code="input_dataset_unhealthy" if dashboard_degraded else None,
            detail=(
                f"aggregated from inputs; {dashboard_status}: {', '.join(dashboard_culprits) or 'unknown'}"[:200]
                if dashboard_degraded else ""
            ),
        )

        # AI analysis freshness (P0-4)
        _record_ai_outcomes(writer, outcomes)

        # History slices
        today = now_utc()[:10]
        risk_row = {
            "date": today,
            "total_score": risk_result.total_score,
            "risk_level": risk_result.risk_level,
            "regime": risk_result.regime,
            "confidence": risk_result.confidence,
            "dim_scores": {d.key: d.score for d in risk_result.dimensions},
        }
        writer.write_slices("risk", [risk_row])
        spy_rows = results.get("histories", {}).get("SPY", [])
        if spy_rows:
            market_row = {"date": spy_rows[-1]["date"], "symbol": "SPY", "close": spy_rows[-1]["close"]}
            writer.write_slices("market", [market_row])

        # Metadata: both files rendered from the one outcome record, last, so a dataset that
        # died mid-run is reported as missing rather than silently omitted.
        _publish_metadata(writer, outcomes, results["provider_status"])
        writer.write_schema_version()  # defaults to the live SCHEMA_VERSION
    except Exception as exc:  # noqa: BLE001
        return False, f"write to disk failed: {exc}"

    # ---- Validate ----
    report = run_data_validation(writer.latest_dir.parent)
    blocking_issues = [*report.errors, *report.blocking_warnings]
    if blocking_issues:
        return False, "validation failed: " + "; ".join(blocking_issues)

    results["risk"] = risk_env
    results["dashboard"] = dashboard_env
    return True, None


# ============================================================
# main
# ============================================================

def _write_failure_report(command: str, results: dict[str, Any], error: str) -> None:
    """Write an ok=False run report — shared by the explicit failure path and the
    crash path (E-5), so a dead run always leaves a record with the reason."""
    write_run_report(
        settings.artifacts_dir,
        command=command, ok=False,
        durations=results.get("durations", {}),
        provider_status=results.get("provider_status", {}),
        degraded=results.get("degraded", []),
        dataset_counts={},
        error=error,
        failed_datasets=[], skipped_datasets=[], degraded_datasets=[],
    )


def _ai_report_reasons(writer: StorageWriter, health: dict[str, list[str]]) -> list[str]:
    """Add bounded AI freshness reasons to collection run reports.

    Collection reports already carry provider notes. AI outputs are out-of-band, so their
    lineage result exists only in freshness metadata; repeat that closed-code explanation
    when the command observed an unhealthy AI dataset.
    """
    raw = writer.read_freshness_raw()
    unhealthy = set(health["failed"]) | set(health["degraded"])
    notes: list[str] = []
    for key in AI_PRODUCED_DATASETS:
        if key not in unhealthy:
            continue
        entry = raw.get("datasets", {}).get(key, {})
        reason = entry.get("reason", {}) if isinstance(entry, dict) else {}
        if not isinstance(reason, dict):
            continue
        code = reason.get("code")
        detail = reason.get("detail", "")
        if code:
            notes.append(f"{key}: {code} — {str(detail)[:200]}"[:240])
    return notes


def _finish_run(command: str, results: dict[str, Any], elapsed: float, health: dict[str, list[str]]) -> int:
    """Write the run report for a successful command and print the summary.

    Shared by `--full` and the single-domain commands: the report is what makes a
    degraded or partial run distinguishable from a clean one (#63 AC). A partial command
    that skipped datasets is never clean — that is the point of the skipped list.
    """
    report_degraded = list(results.get("degraded", []))
    report_degraded.extend(_ai_report_reasons(StorageWriter(settings.data_dir), health))
    write_run_report(
        settings.artifacts_dir,
        command=command,
        ok=True,
        durations=results.get("durations", {}),
        provider_status=results.get("provider_status", {}),
        degraded=report_degraded,
        dataset_counts={"latest": len(list((settings.data_dir / "latest").glob("*.json")))},
        failed_datasets=health["failed"],
        skipped_datasets=health["skipped"],
        degraded_datasets=health["degraded"],
        proxy_discounts=_risk_proxy_discounts(results),
        risk_evidence=_risk_evidence_summary(results),
    )
    _print_summary(command, results, elapsed)
    # E-5: an exit code of 0 on a run where a dataset ended missing is a silent green —
    # the scheduled task must be able to see the failure in the exit status.
    return 1 if health["failed"] else 0


def _risk_proxy_discounts(results: dict[str, Any]) -> list[dict[str, Any]]:
    """The trust discounts that applied to the top drivers (#69), for the run report.

    Each entry names the indicator and the combined discount (1.0 none; proxy discount;
    proxy × degrade factor), so a 0.64 is never an unexplained number.
    """
    risk_env = results.get("risk")
    payload = getattr(risk_env, "payload", None)
    if payload is None:
        return []
    out: list[dict[str, Any]] = []
    for d in getattr(payload, "top_drivers", []):
        if d.discount < 1.0:
            out.append(
                {
                    "indicator_key": d.indicator_key,
                    "dimension_key": d.dimension_key,
                    "label": d.label,
                    "is_proxy": d.is_proxy,
                    "discount": d.discount,
                }
            )
    return out


def _risk_evidence_summary(results: dict[str, Any]) -> dict[str, Any]:
    """Copy the published model evidence state into the operator run report."""
    risk_env = results.get("risk")
    payload = getattr(risk_env, "payload", None)
    if payload is None:
        return {}
    return {
        "state": payload.evidence_state,
        "effective_coverage": payload.evidence_coverage,
        "score": payload.total_score,
        "score_lower_bound": payload.score_lower_bound,
        "score_upper_bound": payload.score_upper_bound,
        "calibration_policy_version": payload.calibration_policy_version,
        "calibration_status": payload.calibration_status,
        "dimensions": [
            {
                "key": dimension.key,
                "state": dimension.evidence_state,
                "coverage": dimension.coverage,
                "effective_weight": dimension.effective_weight,
                "missing_indicators": list(dimension.missing_indicators),
            }
            for dimension in payload.dimensions
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = _resolve_command(args)

    # Config self-check
    try:
        settings.load_universe()
        settings.load_risk_model()
        settings.load_sources()
        settings.load_news_sources()
    except (FileNotFoundError, ValueError) as exc:
        print(f"[pipeline] config loading failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_plan(command, args)
        print("[pipeline] dry-run complete, no files written (no-op normal exit)")
        return 0

    if command == "analysis-only":
        return _run_analysis_only()

    if args.backfill:
        return _run_backfill()

    # E-5: the failure report must stay writable even when collection itself crashes.
    # Without this skeleton, an exception raised by _run_collection left `results`
    # unbound, so the except block's own NameError was swallowed and no run-report
    # was ever written for an early crash.
    results: dict[str, Any] = _empty_results()
    try:
        started = time.monotonic()
        run_started_at = now_utc()
        results = _run_collection(command)

        # Single-domain commands write only the corresponding dataset (unified freshness, P1-7)
        if command == "market-only":
            writer = StorageWriter(settings.data_dir)
            outcomes = RunOutcomes(scope=_run_scope(command))
            market_meta = results.get("market_meta", {})
            # #119: market datasets degrade only on the market collector's own failures, not
            # on the global aggregate (which news/macro/calendar would have extended).
            market_degraded_by_dataset = market_meta.get("degraded_by_dataset", {})
            market_quality = market_meta.get("data_quality_by_dataset", {})
            market_source = market_meta.get("source_updated_at_by_dataset", {})
            _finalize_and_write(
                writer, "equities", results["equities"],
                bool(market_degraded_by_dataset.get("equities", market_meta.get("degraded"))), outcomes,
                                **_provider_kwargs(market_meta, "equities"),
                data_quality=market_quality.get("equities", market_meta.get("data_quality", 1.0)),
                source_updated_at=market_source.get("equities"),
            )
            _finalize_and_write(
                writer, "crypto", results["crypto"],
                bool(market_degraded_by_dataset.get("crypto", market_meta.get("degraded"))), outcomes,
                                **_provider_kwargs(market_meta, "crypto"),
                data_quality=market_quality.get("crypto", market_meta.get("data_quality", 1.0)),
                source_updated_at=market_source.get("crypto"),
            )
            _finalize_and_write(
                writer, "sectors", results["sectors"],
                bool(market_degraded_by_dataset.get("sectors", market_meta.get("degraded"))), outcomes,
                                **_provider_kwargs(market_meta, "sectors"),
                data_quality=market_quality.get("sectors", market_meta.get("data_quality", 1.0)),
                source_updated_at=market_source.get("sectors"),
                detail=market_meta.get("degraded_detail_by_dataset", {}).get("sectors", ""),
            )
            _finalize_and_write(
                writer, "commodities", results["commodities"],
                bool(market_degraded_by_dataset.get("commodities", market_meta.get("degraded"))), outcomes,
                                **_provider_kwargs(market_meta, "commodities"),
                data_quality=market_quality.get("commodities", market_meta.get("data_quality", 1.0)),
                source_updated_at=market_source.get("commodities"),
            )
            _publish_metadata(writer, outcomes, results["provider_status"])
            health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)
            return _finish_run(command, results, time.monotonic() - started, health)

        if command == "macro-only":
            writer = StorageWriter(settings.data_dir)
            outcomes = RunOutcomes(scope=_run_scope(command))
            macro_meta = results.get("macro_meta", {})
            _finalize_and_write(writer, "macro", results["macro"], bool(macro_meta.get("degraded")), outcomes,
                                **_provider_kwargs(macro_meta, None, default="fred"),
                                data_quality=macro_meta.get("data_quality", 1.0),
                                source_updated_at=macro_meta.get("source_updated_at"))
            _record_ai_outcomes(writer, outcomes)
            _publish_metadata(writer, outcomes, results["provider_status"])
            health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)
            return _finish_run(command, results, time.monotonic() - started, health)

        if command == "news-only":
            writer = StorageWriter(settings.data_dir)
            outcomes = RunOutcomes(scope=_run_scope(command))
            news_meta = results.get("news_meta", {})
            _finalize_and_write(writer, "news", results["news"], bool(results.get("news_degraded", False)), outcomes,
                                **_provider_kwargs(news_meta, None, default="rss_news"),
                                data_quality=news_meta.get("data_quality", 1.0),
                                source_updated_at=news_meta.get("source_updated_at"))
            _publish_metadata(writer, outcomes, results["provider_status"])
            health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)
            return _finish_run(command, results, time.monotonic() - started, health)

        # full / fact-layer
        if command == "fact-layer":
            ok, error = _run_fact_layer_only()
        else:
            writer = StorageWriter(settings.data_dir)
            ok, error = _run_risk_and_write(results, writer, command)
            results["durations"]["total"] = time.monotonic() - started

        health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)

        if ok:
            return _finish_run(command, results, results.get("durations", {}).get("total", 0.0), health)

        print(f"[pipeline] failed: {error}", file=sys.stderr)
        _write_failure_report(command, results, error)
        return 1
    except Exception as exc:  # E-5: a crashed run still writes a run-report with a traceback summary
        traceback.print_exc()
        try:
            _write_failure_report(command, results, f"{type(exc).__name__}: {exc}")
        except Exception:  # noqa: BLE001 - never mask the original crash with a report failure
            pass
        return 1


def _run_fact_layer_only() -> tuple[bool, str | None]:
    """Rebuild fact layer only: read latest/*.json and reassemble facts.json."""
    writer = StorageWriter(settings.data_dir)

    def load(name: str, model: Any):
        data = writer.read_latest(name)
        return model.model_validate(data) if data else None

    from pipeline.schemas import (
        CalendarEnvelope,
        CryptoEnvelope,
        EquitiesEnvelope,
        MacroEnvelope,
        NewsEnvelope,
        RiskEnvelope,
        SectorsEnvelope,
    )

    macro = load("macro", MacroEnvelope)
    equities = load("equities", EquitiesEnvelope)
    crypto = load("crypto", CryptoEnvelope)
    news = load("news", NewsEnvelope)
    calendar = load("calendar", CalendarEnvelope)
    risk = load("risk", RiskEnvelope)
    sectors_data = writer.read_latest("sectors")
    sectors = SectorsEnvelope.model_validate(sectors_data) if sectors_data else None

    if not all([macro, equities, crypto, news, calendar, risk]):
        return False, "fact layer rebuild requires latest/*.json to exist (run --full first)"

    builder = FactLayerBuilder()
    # Ruling E (#66): a rebuild is not an observation — preserve the original fetched_at
    # and recompute status from it; never re-stamp the facts as freshly fetched.
    original_generated_at = None
    existing_facts = writer.read_latest("facts")
    if isinstance(existing_facts, dict) and isinstance(existing_facts.get("generated_at"), str):
        original_generated_at = existing_facts["generated_at"]
    if original_generated_at is None:
        # First rebuild without an existing facts.json: the facts aggregate every input,
        # so they are only as fresh as their oldest observation.
        original_generated_at = min(
            str(env.generated_at) for env in (macro, equities, crypto, news, calendar, risk)
        )
    facts = builder.build(
        risk=risk, macro=macro, equities=equities, crypto=crypto, news=news, calendar=calendar,
        sectors=sectors, generated_at=original_generated_at,
    )
    writer.write_standalone("facts", facts.model_dump(mode="json"))
    # Ruling E: the facts preserve the original fetched_at (set on builder.build above),
    # never re-stamping the rebuild as freshly observed. The facts *status* is an
    # aggregation, not a wall-clock comparison of the facts' own timestamp: the fact
    # layer is only as fresh as its stalest input, so we derive it from the per-dataset
    # freshness the builder already assembled. This keeps a rebuild deterministic — fresh
    # inputs always rebuild to a fresh facts regardless of how much real time has passed.
    facts_status = aggregate_freshness(facts.data_freshness.values())
    outcomes = RunOutcomes(scope=_run_scope("fact-layer"))
    culprits = sorted(k for k, v in facts.data_freshness.items() if str(v) == facts_status)
    outcomes.record(
        "factlayer",
        facts_status,
        FreshnessReason(code="ok", detail="rebuilt from latest/*.json")
        if facts_status == "fresh"
        else FreshnessReason(
            code="input_dataset_unhealthy",
            detail=f"rebuilt; {facts_status}: {', '.join(culprits) or 'unknown'}"[:200],
        ),
        provider="fact_layer",
    )
    _record_ai_outcomes(writer, outcomes)
    # No provider was contacted, so provider health is deliberately left as the last real run
    # left it rather than being overwritten with an empty map.
    _publish_metadata(writer, outcomes)
    return True, None


def _merge_news_translations(
    writer: StorageWriter,
    collector: NewsCollector,
    news: Any,
    translations_path: Path,
) -> Any:
    """Merge news.zh-translations.json into a NEWS PAYLOAD and record the outcome (P1-6).

    Shared by the full-refresh and --analysis-only call sites (#81: the second hand-rolled
    copy passed a NewsEnvelope where this takes the payload — one block cannot drift).
    Returns the merged payload, or None when no translations file exists ("missing" is
    recorded here and the caller keeps its dataset unchanged).
    """
    if not translations_path.exists():
        writer.record_translations(
            "missing", 0, "news.zh-translations.json not found (AI did not produce Chinese translation)"
        )
        return None
    from pipeline.schemas import NewsTranslationsDataset

    import json as _json

    translations = NewsTranslationsDataset.model_validate(_json.loads(translations_path.read_text(encoding="utf-8")))
    merged = collector.merge_translations(news, translations)
    merged_count = sum(1 for it in merged.items if it.title_zh)
    writer.record_translations("merged", merged_count, "news.zh-translations.json merged into news.json")
    return merged


def _run_analysis_only() -> int:
    """AI analysis file validation + Chinese translation merge (architecture §1.5 steps 3/4)."""
    writer = StorageWriter(settings.data_dir)
    outcomes = RunOutcomes(scope=_run_scope("analysis-only"))
    analysis_valid = _record_ai_outcomes(writer, outcomes)
    if not analysis_valid:
        _publish_metadata(writer, outcomes)
        _write_analysis_only_report(writer, outcomes)
        print("[pipeline] analysis-only: AI pair was not promoted; freshness recorded as degraded", file=sys.stderr)
        return 0

    # Merge Chinese translation into news.json (P1-6: record merge status)
    news_data = writer.read_latest("news")
    if news_data:
        from pipeline.schemas import NewsEnvelope

        news = NewsEnvelope.model_validate(news_data)
        collector = NewsCollector(build_registry(settings), settings)
        # #81: the shared helper takes the PAYLOAD (merge_translations iterates
        # `news.items`, which an envelope does not have) and re-wrap the result —
        # the old hand-rolled copy passed the envelope and never merged.
        merged_payload = _merge_news_translations(
            writer, collector, news.payload, settings.data_dir / "latest" / "news.zh-translations.json"
        )
        if merged_payload is not None:
            writer.write_dataset("news", news.model_copy(update={"payload": merged_payload}))
            print("[pipeline] analysis-only: Chinese translation merged into news.json")

    outcomes = RunOutcomes(scope=_run_scope("analysis-only"))
    _record_ai_outcomes(writer, outcomes)
    _publish_metadata(writer, outcomes)
    _write_analysis_only_report(writer, outcomes)
    print("[pipeline] analysis-only: validation passed ✓")
    return 0


def _period_for_days(days: int) -> str:
    """Map a warm-up window to the coarsest provider period that covers it (#188).

    The CLI advertises 30-90 days; before this mapping the fetch hardcoded "1y", so an
    operator asking for a 30-day warm-up silently spent a year of quota.
    """
    if days <= 35:
        return "1mo"
    if days <= 100:
        return "3mo"
    if days <= 200:
        return "6mo"
    return "1y"


def _run_backfill(window_days: int = 90) -> int:
    """Warm-up backfill of the requested window in days (except FedWatch, architecture §1.7).

    Pull benchmark + all US equity history; history/market writes only the SPY benchmark
    series (to avoid different symbols overwriting each other when merging by date), while
    other symbols only warm the last-good cache for quote use.

    Per-symbol failures stay non-interrupting (degradation contract) but are no longer
    stdout-only (#188): they land in artifacts/logs/run-report-*.json as failed_datasets,
    so a partially-warmed cache is visible to operators without touching the published
    metadata files.
    """
    period = _period_for_days(window_days)
    print(f"[pipeline] backfill: last {window_days} days (provider period {period}; FedWatch accumulates from launch)")
    started = time.monotonic()
    registry = build_registry(settings)
    writer = StorageWriter(settings.data_dir)
    universe = AssetUniverse.load(settings)

    failed: list[str] = []
    for symbol in ["SPY", "IWM", "SOXX", *[a.symbol for a in universe.us_equities]]:
        symbol_started = time.monotonic()
        try:
            out = registry.call("quotes", "get_history", f"backfill_{symbol}", args=(symbol, period))
            rows = out["result"].rows
            if symbol == "SPY":
                writer.write_slices("market", [{"date": r["date"], "symbol": symbol, "close": r["close"]} for r in rows if r.get("close") is not None])
            print(f"  {symbol}: {len(rows)} rows backfilled")
        except Exception as exc:  # noqa: BLE001 - degradation contract: one symbol never blocks the rest
            failed.append(symbol)
            print(f"  {symbol}: backfill failed (degraded, not interrupted): {exc}")

    write_run_report(
        settings.artifacts_dir,
        command="backfill",
        ok=True,
        durations={"total": time.monotonic() - started},
        provider_status={},
        degraded=[],
        dataset_counts={},
        failed_datasets=failed or None,
    )
    if failed:
        print(f"[pipeline] backfill: complete WITH FAILURES ({', '.join(failed)}); see run-report")
    else:
        print("[pipeline] backfill: complete")
    return 0


#: Public seam for scripts/backfill.py — entry points must not reach into underscore-private
#: pipeline API, where any refactor breaks them silently (#188).
run_backfill = _run_backfill


def _print_plan(command: str, args: argparse.Namespace) -> None:
    print("Market Risk Dashboard pipeline run plan")
    print(f"  command     : {command}")
    print(f"  language    : {args.locale or 'bilingual'}")
    print(f"  dry-run     : {args.dry_run}")
    print(f"  backfill    : {args.backfill}")
    print(f"  config dir  : {settings.config_dir}")
    print(f"  data dir    : {settings.data_dir}")
    print("  ⚠ T03: real collection implemented; dry-run does not touch the network or disk.")


def _print_summary(command: str, results: dict[str, Any], elapsed: float) -> None:
    counts: dict[str, int] = {}
    for key, env in results.items():
        payload = getattr(env, "payload", None)
        if payload is None:
            continue
        for attr in ("assets", "items", "events", "sectors"):
            if hasattr(payload, attr):
                counts[key] = len(getattr(payload, attr))
                break
    print(f"[pipeline] {command} completed ({elapsed:.1f}s)")
    print(f"  dataset counts: {counts}")
    print(f"  degraded      : {len(results.get('degraded', []))} site(s)")
    if results.get("degraded"):
        for d in results["degraded"][:10]:
            print(f"    - {d}")
    risk = results.get("risk")
    print(f"  risk score    : {risk.payload.total_score if risk else None}")


if __name__ == "__main__":
    raise SystemExit(main())
