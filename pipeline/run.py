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
from pathlib import Path
from typing import Any

from pipeline import __version__
from pipeline.collectors import CalendarCollector, MacroCollector, MarketCollector, NewsCollector
from pipeline.factlayer import FactLayerBuilder
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
from pipeline.schemas.envelope import assemble_envelope
from pipeline.settings import settings
from pipeline.storage import StorageWriter
from pipeline.universe import AssetUniverse
from pipeline.utils import now_utc
from pipeline.validation.freshness import finalize_freshness
from pipeline.validation.validate_all import validate_all

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
    histories: dict[str, list[dict[str, Any]]],
    qualities: list[float],
    prev_total_score: float | None,
    prev_dim_scores: dict[str, float] | None,
    risk_history: list[dict[str, Any]],
    series_history: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Assemble the collected results into the context required by RiskModel.score."""
    from pipeline.indicators.breadth import breadth_snapshot
    from pipeline.indicators.trend import trend_snapshot

    breadth = breadth_snapshot(histories)
    trend = trend_snapshot(histories)

    # Cross-asset confirmation signals (MVP simplified to 7 items)
    vix = _macro_value(macro, "rates", "vixcls")
    hy = _macro_value(macro, "credit", "bamlh0a0hym2")
    dxy = _macro_value(macro, "fx", "dtwexbgs")
    real_rate = _macro_value(macro, "rates", "dfii10")
    spy_change = _latest_change(histories.get("SPY"))
    iwm_relative = breadth.get("small_cap_relative")
    btc_change = crypto.payload.assets[0].change_1d if crypto.payload.assets else None

    signals = [
        spy_change is not None and spy_change < 0,
        hy is not None and hy > 4.0,
        dxy is not None and dxy > 105,
        real_rate is not None and real_rate > 1.5,
        btc_change is not None and btc_change < 0,
        iwm_relative is not None and iwm_relative < 0,
    ]
    confirmation = round(sum(1 for s in signals if s) / len(signals), 4) if signals else None

    data_quality = sum(qualities) / len(qualities) if qualities else 1.0
    return {
        "macro": macro.payload,
        "equities": equities.payload,
        "crypto": crypto.payload,
        "histories": histories,
        "breadth": breadth,
        "trend": trend,
        "cross_asset": {"confirmation": confirmation},
        "data_quality": round(data_quality, 4),
        "series_history": series_history,
        "_prev_total_score": prev_total_score,
        "_prev_dim_scores": prev_dim_scores,
        "_risk_history": risk_history,
    }


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

#: Every dataset a `--full` run is expected to publish.
FULL_RUN_DATASETS: tuple[str, ...] = (
    "macro", "equities", "sectors", "crypto", "news", "calendar", "risk", "facts", "dashboard",
)

#: Datasets each command attempts. Anything in FULL_RUN_DATASETS and not listed here was
#: skipped by design — still worth naming, because a `--market-only` run leaves most of
#: the dashboard on yesterday's data and an operator should not have to infer that.
COMMAND_DATASETS: dict[str, tuple[str, ...]] = {
    "full": FULL_RUN_DATASETS,
    "market-only": ("equities", "sectors", "crypto"),
    "macro-only": ("macro",),
    "news-only": ("news",),
    "fact-layer": ("facts",),
}

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

#: Envelope model per published dataset (the single assembly path maps name -> model).
_ENVELOPE_MODELS: dict[str, type[BaseEnvelope]] = {
    "macro": MacroEnvelope,
    "equities": EquitiesEnvelope,
    "sectors": SectorsEnvelope,
    "crypto": CryptoEnvelope,
    "news": NewsEnvelope,
    "calendar": CalendarEnvelope,
    "risk": RiskEnvelope,
    "dashboard": DashboardEnvelope,
}


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
) -> BaseEnvelope:
    """Build the envelope for `name` through the single assembly path (#64/#65).

    Freshness is computed by :func:`pipeline.schemas.envelope.assemble_envelope` via
    ``finalize_freshness`` — the only producer. `provider` is the resolved provider that
    actually served the dataset (#65): it becomes the envelope's source and provenance.
    """
    return assemble_envelope(
        _ENVELOPE_MODELS[name],
        payload,
        dataset=name,
        degraded=degraded,
        provider=provider,
        used_fallback=used_fallback,
        from_cache=from_cache,
        data_quality=data_quality,
        generated_at=generated_at,
        source_updated_at=source_updated_at,
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


def _write_finalized(writer: StorageWriter, name: str, env: BaseEnvelope, extra_reason: str = "") -> BaseEnvelope:
    """Persist an already-assembled envelope and record its freshness metadata."""
    writer.write_dataset(name, env)
    status = env.freshness_status
    reason = {"degraded": "degraded", "missing": "missing"}.get(status, "ok")
    if extra_reason:
        reason = f"{reason} ({extra_reason})"
    writer.update_freshness(name, status, reason)
    return env


def _finalize_and_write(
    writer: StorageWriter,
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
    extra_reason: str = "",
) -> BaseEnvelope:
    """Assemble through the single path, write, and update metadata/freshness.json (#64/#65).

    Collectors no longer fill freshness_status themselves; this recomputes against the
    expected frequency from sources.yaml (fresh/delayed/stale/missing/degraded), then
    persists to the envelope and freshness.json. The resolved provider (and whether it was a
    fallback / cache replay) is published as source + provenance (#65).
    """
    env = _assemble(name, payload, degraded, provider=provider,
                    used_fallback=used_fallback, from_cache=from_cache,
                    data_quality=data_quality, generated_at=generated_at,
                    source_updated_at=source_updated_at)
    return _write_finalized(writer, name, env, extra_reason)


def _write_analysis_freshness(writer: StorageWriter) -> None:
    """AI analysis freshness (P0-4, architecture §1.5): missing/failed → analysis=degraded."""
    zh = writer.latest_dir / "analysis.zh-CN.json"
    en = writer.latest_dir / "analysis.en.json"
    if not (zh.exists() and en.exists()):
        writer.update_freshness(
            "analysis", "degraded", "AI analysis files missing (no quota/exhausted retries) → degraded"
        )
        return
    import json as _json

    generated_at = ""
    try:
        for path in (zh, en):
            data = _json.loads(path.read_text(encoding="utf-8"))
            generated_at = max(generated_at, str(data.get("generated_at", "")))
    except (_json.JSONDecodeError, OSError):
        generated_at = ""
    status = finalize_freshness("analysis", generated_at or None, False)
    reason = "ok" if status == "fresh" else status
    writer.update_freshness("analysis", status, reason)


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
        for s in sectors.payload.sectors:
            sector_performance.append({"key": s.key, "label": s.label, "label_zh": s.label_zh, "change_1d": s.change_1d})
        for t in sectors.payload.themes:
            sector_performance.append({"key": t.key, "label": t.label, "label_zh": t.label_zh, "change_1d": t.change_1d})

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

def _run_collection(command: str) -> dict[str, Any]:
    """Run collection according to the command, returning collected results and durations."""
    started = time.monotonic()
    registry = build_registry(settings)
    universe = AssetUniverse.load(settings)
    writer = StorageWriter(settings.data_dir)

    results: dict[str, Any] = {
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
            sectors=market["sectors"],
            histories=market["histories"],
        )
        results["market_meta"] = market
        results["degraded"].extend(market["degraded"])
        results["provider_status"].update(market["provider_status"])
        results["qualities"].append(market["data_quality"])
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
        results["qualities"].append(cal_meta["data_quality"])
        results["durations"]["calendar"] = time.monotonic() - t0

    if need_news:
        t0 = time.monotonic()
        ncc = NewsCollector(registry, settings)
        news, news_meta = ncc.collect()
        # Merge AI Chinese translations (if present) + record merge status (P1-6)
        translations_path = settings.data_dir / "latest" / "news.zh-translations.json"
        if translations_path.exists():
            from pipeline.schemas import NewsTranslationsDataset

            import json as _json

            translations = NewsTranslationsDataset.model_validate(
                _json.loads(translations_path.read_text(encoding="utf-8"))
            )
            news = ncc.merge_translations(news, translations)
            merged_count = sum(1 for it in news.items if it.title_zh)
            writer.record_translations("merged", merged_count, "news.zh-translations.json merged into news.json")
        else:
            writer.record_translations("missing", 0, "news.zh-translations.json not found (AI did not produce Chinese translation)")
        results["news"] = news
        results["news_meta"] = news_meta
        results["news_degraded"] = bool(news_meta["degraded"])
        results["degraded"].extend(news_meta["degraded"])
        results["provider_status"]["news"] = {
            "provider": news_meta.get("provider", "rss_news"),
            "sources": news_meta.get("source_status", {}),
        }
        results["qualities"].append(news_meta["data_quality"])
        results["durations"]["news"] = time.monotonic() - t0

    results["durations"]["collection"] = time.monotonic() - started
    return results


def _run_risk_and_write(results: dict[str, Any], writer: StorageWriter, command: str) -> tuple[bool, str | None]:
    """Compute risk + fact layer + dashboard + write + unified freshness + validate. Returns (ok, error)."""
    degraded = bool(results["degraded"])
    market_meta = results.get("market_meta", {})
    macro_meta = results.get("macro_meta", {})
    news_meta = results.get("news_meta", {})
    calendar_meta = results.get("calendar_meta", {})
    try:
        # #64/#65: assemble every envelope through the single path (freshness = finalize_freshness;
        # source + provenance = the resolved provider from the collector's outcome).
        macro_outcome = macro_meta.get("provider", {"provider": "unavailable", "used_fallback": False, "from_cache": False})
        macro = _assemble("macro", results["macro"], bool(macro_meta.get("degraded")),
                          provider=str(macro_outcome.get("provider", "unavailable")),
                          used_fallback=bool(macro_outcome.get("used_fallback", False)),
                          from_cache=bool(macro_outcome.get("from_cache", False)),
                          data_quality=macro_meta.get("data_quality", 1.0))
        equities = _assemble("equities", results["equities"], degraded,
                             **_provider_kwargs(market_meta, "equities"),
                             data_quality=market_meta.get("data_quality", 1.0))
        sectors = _assemble("sectors", results["sectors"], degraded,
                            **_provider_kwargs(market_meta, "sectors"),
                            data_quality=market_meta.get("data_quality", 1.0))
        crypto = _assemble("crypto", results["crypto"], degraded,
                           **_provider_kwargs(market_meta, "crypto"),
                           data_quality=market_meta.get("data_quality", 1.0))
        news = _assemble("news", results["news"], bool(results.get("news_degraded", False)),
                         **_provider_kwargs(news_meta, None, default="rss_news"),
                         data_quality=news_meta.get("data_quality", 1.0))
        calendar = _assemble("calendar", results["calendar"], bool(results.get("calendar_degraded", False)),
                             **_provider_kwargs(calendar_meta, None, default="fmp"),
                             data_quality=calendar_meta.get("data_quality", 1.0))

        risk_model = RiskModel(settings)
        prev_score, prev_dims, risk_history = _read_prev_risk(writer)
        ctx = _build_risk_context(
            macro=macro,
            equities=equities,
            crypto=crypto,
            histories=results.get("histories", {}),
            qualities=results["qualities"],
            prev_total_score=prev_score,
            prev_dim_scores=prev_dims,
            risk_history=risk_history,
            series_history=results.get("series_history", {}),
        )
        risk_result = risk_model.score(ctx)
        risk_env = _assemble("risk", risk_result, degraded,
                             provider="risk_model",
                             data_quality=ctx["data_quality"])

        builder = FactLayerBuilder()
        facts = builder.build(
            risk=risk_env,
            macro=macro,
            equities=equities,
            crypto=crypto,
            news=news,
            calendar=calendar,
            sectors=sectors,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"risk/fact layer computation failed: {exc}"

    # ---- Write (persist after unified freshness determination, P1-7) ----
    try:
        macro = _write_finalized(writer, "macro", macro)
        equities = _write_finalized(writer, "equities", equities)
        sectors = _write_finalized(writer, "sectors", sectors)
        crypto = _write_finalized(writer, "crypto", crypto)
        news = _write_finalized(writer, "news", news)
        calendar = _write_finalized(writer, "calendar", calendar)
        risk_env = _write_finalized(writer, "risk", risk_env)
        writer.write_standalone("facts", facts.model_dump(mode="json"))
        facts_status = "degraded" if degraded else finalize_freshness("facts", str(risk_env.generated_at), False)
        writer.update_freshness("facts", facts_status, "degraded" if facts_status == "degraded" else "ok")

        # dashboard (P1-5)
        dashboard_payload = _build_dashboard(
            risk_env=risk_env,
            equities=equities,
            crypto=crypto,
            sectors=sectors,
            calendar=calendar,
        )
        dashboard_env = _finalize_and_write(
            writer, "dashboard", dashboard_payload, degraded,
            provider="risk_model",
            data_quality=round(ctx["data_quality"], 3),
        )

        # AI analysis freshness (P0-4)
        _write_analysis_freshness(writer)

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

        # Metadata
        writer.write_sources_metadata(results["provider_status"])
        writer.write_schema_version("1.0.0")
    except Exception as exc:  # noqa: BLE001
        return False, f"write to disk failed: {exc}"

    # ---- Validate ----
    report = validate_all(writer.latest_dir, strict=False)
    if not report.ok:
        return False, "validation failed: " + "; ".join(report.issues)

    results["risk"] = risk_env
    results["dashboard"] = dashboard_env
    return True, None


# ============================================================
# main
# ============================================================

def _finish_run(command: str, results: dict[str, Any], elapsed: float, health: dict[str, list[str]]) -> int:
    """Write the run report for a successful command and print the summary.

    Shared by `--full` and the single-domain commands: the report is what makes a
    degraded or partial run distinguishable from a clean one (#63 AC). A partial command
    that skipped datasets is never clean — that is the point of the skipped list.
    """
    write_run_report(
        settings.artifacts_dir,
        command=command,
        ok=True,
        durations=results.get("durations", {}),
        provider_status=results.get("provider_status", {}),
        degraded=results.get("degraded", []),
        dataset_counts={"latest": len(list((settings.data_dir / "latest").glob("*.json")))},
        failed_datasets=health["failed"],
        skipped_datasets=health["skipped"],
        degraded_datasets=health["degraded"],
        proxy_discounts=_risk_proxy_discounts(results),
    )
    _print_summary(command, results, elapsed)
    return 0


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

    started = time.monotonic()
    run_started_at = now_utc()
    results = _run_collection(command)

    # Single-domain commands write only the corresponding dataset (unified freshness, P1-7)
    if command == "market-only":
        writer = StorageWriter(settings.data_dir)
        market_meta = results.get("market_meta", {})
        degraded = bool(results["degraded"])
        _finalize_and_write(writer, "equities", results["equities"], degraded,
                            **_provider_kwargs(market_meta, "equities"),
                            data_quality=market_meta.get("data_quality", 1.0))
        _finalize_and_write(writer, "crypto", results["crypto"], degraded,
                            **_provider_kwargs(market_meta, "crypto"),
                            data_quality=market_meta.get("data_quality", 1.0))
        _finalize_and_write(writer, "sectors", results["sectors"], degraded,
                            **_provider_kwargs(market_meta, "sectors"),
                            data_quality=market_meta.get("data_quality", 1.0))
        writer.write_sources_metadata(results["provider_status"])
        health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)
        return _finish_run(command, results, time.monotonic() - started, health)

    if command == "macro-only":
        writer = StorageWriter(settings.data_dir)
        macro_meta = results.get("macro_meta", {})
        _finalize_and_write(writer, "macro", results["macro"], bool(macro_meta.get("degraded")),
                            **_provider_kwargs(macro_meta, None, default="fred"),
                            data_quality=macro_meta.get("data_quality", 1.0))
        _write_analysis_freshness(writer)
        writer.write_sources_metadata(results["provider_status"])
        health = dataset_health(StorageWriter(settings.data_dir), command, run_started_at=run_started_at)
        return _finish_run(command, results, time.monotonic() - started, health)

    if command == "news-only":
        writer = StorageWriter(settings.data_dir)
        news_meta = results.get("news_meta", {})
        _finalize_and_write(writer, "news", results["news"], bool(results.get("news_degraded", False)),
                            **_provider_kwargs(news_meta, None, default="rss_news"),
                            data_quality=news_meta.get("data_quality", 1.0))
        writer.write_sources_metadata(results["provider_status"])
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
    write_run_report(
        settings.artifacts_dir,
        command=command, ok=False,
        durations=results.get("durations", {}),
        provider_status=results.get("provider_status", {}),
        degraded=results.get("degraded", []),
        dataset_counts={}, error=error,
        failed_datasets=health["failed"],
        skipped_datasets=health["skipped"],
        degraded_datasets=health["degraded"],
    )
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
    # Ruling E: recompute the freshness status from the preserved fetched_at, never re-stamp
    # the rebuild as freshly observed.
    facts_status = finalize_freshness("facts", original_generated_at, False)
    writer.update_freshness("facts", facts_status, "rebuilt")
    _write_analysis_freshness(writer)
    return True, None


def _run_analysis_only() -> int:
    """AI analysis file validation + Chinese translation merge (architecture §1.5 steps 3/4)."""
    import json as _json

    from pipeline.analysis.validate import validate_analysis_pair
    from pipeline.analysis.contract import analysis_path, input_path
    from pipeline.schemas import NewsTranslationsDataset

    zh_path = analysis_path("zh-CN")
    en_path = analysis_path("en")
    facts_path = input_path("facts")

    if not zh_path.exists() or not en_path.exists():
        print("[pipeline] analysis-only: analysis file missing (validate after AI automation output), skipped", file=sys.stderr)
        writer = StorageWriter(settings.data_dir)
        writer.update_freshness("analysis", "degraded", "AI analysis files missing (no quota/exhausted retries) → degraded")
        return 0

    try:
        issues, _, _ = validate_analysis_pair(zh_path, en_path, facts_path if facts_path.exists() else None)
    except Exception as exc:  # noqa: BLE001
        print(f"[pipeline] analysis-only: validation failed: {exc}", file=sys.stderr)
        return 1

    if issues:
        print("[pipeline] analysis-only: bilingual consistency failed:")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    # Merge Chinese translation into news.json (P1-6: record merge status)
    writer = StorageWriter(settings.data_dir)
    news_data = writer.read_latest("news")
    translations_path = settings.data_dir / "latest" / "news.zh-translations.json"
    if news_data and translations_path.exists():
        from pipeline.schemas import NewsEnvelope

        news = NewsEnvelope.model_validate(news_data)
        translations = NewsTranslationsDataset.model_validate(_json.loads(translations_path.read_text(encoding="utf-8")))
        collector = NewsCollector(build_registry(settings), settings)
        merged = collector.merge_translations(news, translations)
        merged_count = sum(1 for it in merged.payload.items if it.title_zh)
        writer.write_dataset("news", merged)
        writer.record_translations("merged", merged_count, "analysis-only merged news.zh-translations.json into news.json")
        print("[pipeline] analysis-only: Chinese translation merged into news.json")
    elif news_data:
        writer.record_translations("missing", 0, "news.zh-translations.json not found (AI did not produce Chinese translation)")

    writer.update_freshness("analysis", "fresh", "AI analysis file validation passed")
    print("[pipeline] analysis-only: validation passed ✓")
    return 0


def _run_backfill() -> int:
    """Warm-up backfill of 30-90 days (except FedWatch, architecture §1.7/review P1-5).

    Pull benchmark + all US equity history; history/market writes only the SPY benchmark
    series (to avoid different symbols overwriting each other when merging by date), while
    other symbols only warm the last-good cache for quote use.
    """
    print("[pipeline] backfill: backfilling 30-90 days of history…")
    registry = build_registry(settings)
    writer = StorageWriter(settings.data_dir)
    universe = AssetUniverse.load(settings)

    for symbol in ["SPY", "IWM", "SOXX", *[a.symbol for a in universe.us_equities]]:
        try:
            out = registry.call("quotes", "get_history", f"backfill_{symbol}", args=(symbol, "1y"))
            rows = out["result"].rows
            if symbol == "SPY":
                writer.write_slices("market", [{"date": r["date"], "symbol": symbol, "close": r["close"]} for r in rows if r.get("close") is not None])
            print(f"  {symbol}: {len(rows)} rows backfilled")
        except Exception as exc:  # noqa: BLE001
            print(f"  {symbol}: backfill failed (degraded, not interrupted): {exc}")
    print("[pipeline] backfill: complete")
    return 0


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
