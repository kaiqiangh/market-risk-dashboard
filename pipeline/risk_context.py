from __future__ import annotations

from typing import Any

from pipeline.schemas import registry as dataset_registry
from pipeline.storage import StorageWriter

#: One source for the gated set (#192): was restated as two literals that could drift.
GATED_SIGNALS = frozenset({"cyclicals_defensives_relative", "hy_treasury_relative"})


def build_risk_context(
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
    production_signals = [row for row in signal_rows if row["key"] not in GATED_SIGNALS]
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
        "production_scoring": key not in GATED_SIGNALS,
    }


def read_prev_risk(writer: StorageWriter) -> tuple[float | None, dict[str, float] | None, list[dict[str, Any]]]:
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


