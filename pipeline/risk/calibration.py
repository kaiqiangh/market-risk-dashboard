"""Offline calibration engine (architecture §1.8 frozen: 2008/2018/2020 three segments).

All data is freely available: FRED VIXCLS/BAMLH0A0HYM2/DGS10 + yfinance SPX history.
Evaluation metrics (PRD §15 subset): early-warning lead time, risk score change speed,
maximum drawdown, future 5/10/20/30-day volatility, risk level stability.
Calibration red line: before calibration completes, the UI must not call the risk score
an "exact crash probability".

#72: this harness evaluates the HEURISTIC FALLBACK path (`heuristic_risk_score`), not
the production percentile path in `compute_indicator_score` (pipeline/risk/scoring.py).
Every output carries `scoring_path: "heuristic_fallback"` so the results are never
mistaken for production behaviour. Sign convention: `early_warning_days_vs_peak` is
POSITIVE when the warning fired BEFORE the peak (days early).
"""

from __future__ import annotations

import hashlib
import json
import math
from types import SimpleNamespace
from typing import Any

from pipeline.risk.scoring import heuristic_risk_score
from pipeline.schemas import MacroDataset, MacroIndicator

CALIBRATION_WINDOWS = {
    "2008": {"start": "2008-08-01", "end": "2009-03-31", "note": "2008 financial crisis"},
    "2018": {"start": "2018-09-01", "end": "2018-12-31", "note": "2018 Q4 selloff"},
    "2020": {"start": "2020-02-01", "end": "2020-04-30", "note": "COVID crash"},
}

# These are calibration-only evaluation constants. They do not alter the live model's
# weights, thresholds, or confidence policy.
PRODUCTION_CALIBRATION_HORIZONS = (5, 10, 20, 30)
CALIBRATION_ALERT_SCORE = 60.0
CALIBRATION_EVENT_HORIZON = 20
CALIBRATION_EVENT_DRAWDOWN = -0.10
CALIBRATION_MACRO_GROUPS = {
    "dgs10": "rates",
    "dgs2": "rates",
    "dfii10": "rates",
    "dtwexbgs": "fx",
    "bamlh0a0hym2": "credit",
    "bamlc0a0cm": "credit",
    "vixcls": "volatility",
    "walcl": "liquidity",
    "rrpontsyd": "liquidity",
}
CALIBRATION_MACRO_LABELS = {
    "dgs10": "10Y Yield",
    "dgs2": "2Y Yield",
    "dfii10": "10Y Real Rate",
    "dtwexbgs": "Dollar Index",
    "bamlh0a0hym2": "HY OAS",
    "bamlc0a0cm": "IG OAS",
    "vixcls": "VIX",
    "walcl": "Fed Balance Sheet",
    "rrpontsyd": "Reverse Repo",
}


def composite_score(vix: float | None, hy: float | None, drawdown: float | None) -> float:
    """Simplified composite risk score (0-100): weighted combination of VIX + HY OAS + drawdown."""
    scores = [
        heuristic_risk_score("vix", vix),
        heuristic_risk_score("hy_oas", hy),
        heuristic_risk_score("drawdown_52w", drawdown),
    ]
    present = [s for s in scores if s is not None]
    if not present:
        return 50.0
    return round(sum(present) / len(present), 2)


def evaluate_segment(
    dates: list[str],
    vix_series: list[float | None],
    hy_series: list[float | None],
    spx_series: list[float],
    segment: str,
) -> dict[str, Any]:
    """Compute evaluation metrics for a single segment window."""
    scores: list[float] = []
    for i in range(len(dates)):
        drawdown = _drawdown(spx_series[: i + 1])
        scores.append(composite_score(vix_series[i] if i < len(vix_series) else None,
                                      hy_series[i] if i < len(hy_series) else None,
                                      drawdown))

    peak_idx = spx_series.index(max(spx_series)) if spx_series else 0
    max_dd = _max_drawdown(spx_series) if spx_series else None

    # Early warning (#72): days BEFORE the peak when the risk score first reaches ≥ 60.
    # Positive = warned early (score crossed 60 before the peak); negative = warned late.
    early_warning_days: int | None = None
    for i, s in enumerate(scores):
        if s >= 60:
            early_warning_days = peak_idx - i
            break

    # Change speed: fewest days for the risk score to go from 40 → 60
    speed_days: int | None = None
    start_idx: int | None = None
    for i, s in enumerate(scores):
        if s >= 40 and start_idx is None:
            start_idx = i
        if start_idx is not None and s >= 60:
            speed_days = i - start_idx
            break

    # Future 5/10/20/30-day volatility (after the peak)
    future_vol: dict[str, float | None] = {}
    for horizon in (5, 10, 20, 30):
        future_vol[f"vol_{horizon}d"] = _future_vol(spx_series, peak_idx, horizon)

    # Risk level stability: number of switches across the 40/60 thresholds
    switches = 0
    prev_level = _level(scores[0]) if scores else None
    for s in scores:
        level = _level(s)
        if level != prev_level:
            switches += 1
            prev_level = level

    return {
        "segment": segment,
        "note": CALIBRATION_WINDOWS[segment]["note"],
        "scoring_path": "heuristic_fallback",
        "n_days": len(dates),
        "max_drawdown_pct": round(max_dd * 100.0, 2) if max_dd is not None else None,
        "early_warning_days_vs_peak": early_warning_days,
        "speed_40_to_60_days": speed_days,
        "future_vol": future_vol,
        "level_switches": switches,
        "score_first": scores[0] if scores else None,
        "score_max": max(scores) if scores else None,
        "score_last": scores[-1] if scores else None,
    }


def _drawdown(series: list[float]) -> float | None:
    if not series:
        return None
    peak = max(series)
    if peak == 0:
        return None
    return (series[-1] - peak) / peak


def _max_drawdown(series: list[float]) -> float | None:
    """Maximum drawdown within the window (worst peak→trough value, architecture §15 evaluation metric)."""
    if not series:
        return None
    peak = series[0]
    worst = 0.0
    for value in series:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value - peak) / peak)
    return worst


def _future_vol(series: list[float], start: int, horizon: int) -> float | None:
    import math

    window = series[start : start + horizon]
    if len(window) < 3:
        return None
    returns = [(window[i] - window[i - 1]) / window[i - 1] for i in range(1, len(window)) if window[i - 1] != 0]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return round(math.sqrt(var) * 100.0, 2)


def _level(score: float) -> str:
    if score >= 80:
        return "severe"
    if score >= 60:
        return "high"
    if score >= 40:
        return "caution"
    return "low"


# ---------------------------------------------------------------------------
# Production-path point-in-time replay (#141)
# ---------------------------------------------------------------------------

def normalize_calibration_panel(panel: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the columnar panel consumed by the replay engine.

    ``dates`` includes warm-up observations as well as evaluated observations. A row with
    ``evaluate=false`` is available to the percentile/trend lookback but never appears as a
    scored result. This is the explicit boundary that prevents future observations leaking
    into an earlier score.
    """
    if not isinstance(panel, dict):
        raise ValueError("calibration panel must be an object")
    dates = [str(value) for value in panel.get("dates", [])]
    if not dates or dates != sorted(dates) or len(set(dates)) != len(dates):
        raise ValueError("calibration panel dates must be unique, non-empty, and ascending")
    count = len(dates)
    evaluate = [bool(value) for value in panel.get("evaluate", [True] * count)]
    regimes = [str(value) for value in panel.get("regimes", ["unclassified"] * count)]
    if len(evaluate) != count or len(regimes) != count:
        raise ValueError("calibration panel evaluate/regimes must match dates")
    if not any(evaluate):
        raise ValueError("calibration panel must contain at least one evaluated row")

    series: dict[str, dict[str, list[float | None]]] = {"macro": {}, "market": {}}
    for category in series:
        raw_series = panel.get(category, {})
        if not isinstance(raw_series, dict):
            raise ValueError(f"calibration panel {category} must be an object")
        for key, raw_values in raw_series.items():
            if not isinstance(raw_values, list) or len(raw_values) != count:
                raise ValueError(f"calibration panel {category}.{key} must match dates")
            values: list[float | None] = []
            for value in raw_values:
                if value is None:
                    values.append(None)
                elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                    values.append(float(value))
                else:
                    raise ValueError(f"calibration panel {category}.{key} contains a non-finite value")
            series[category][str(key).lower()] = values

    if "spy" not in series["market"]:
        raise ValueError("calibration panel must include market.SPY")
    metadata = panel.get("source_metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("calibration panel source_metadata must be an object")
    missing = {
        category: {key: sum(value is None for value in values) for key, values in values_by_key.items()}
        for category, values_by_key in series.items()
    }
    return {
        "panel_version": str(panel.get("panel_version", "1.0.0")),
        "dates": dates,
        "evaluate": evaluate,
        "regimes": regimes,
        "macro": series["macro"],
        "market": series["market"],
        "source_metadata": metadata,
        "missing_observations": missing,
    }


def _macro_payload(panel: dict[str, Any], index: int) -> MacroDataset:
    groups: dict[str, list[MacroIndicator]] = {
        "rates": [],
        "credit": [],
        "volatility": [],
        "inflation": [],
        "labor": [],
        "liquidity": [],
        "fx": [],
    }
    for key, group in CALIBRATION_MACRO_GROUPS.items():
        values = panel["macro"].get(key, [])
        value = values[index] if values else None
        groups[group].append(
            MacroIndicator(
                key=key,
                label=CALIBRATION_MACRO_LABELS[key],
                value=value,
                source="calibration_panel",
                status="fresh" if value is not None else "missing",
            )
        )
    return MacroDataset(**groups, fedwatch=None)


def _point_in_time_series_history(panel: dict[str, Any], index: int) -> dict[str, list[dict[str, Any]]]:
    return {
        key: [
            {"date": panel["dates"][row_index], "value": value}
            for row_index, value in enumerate(values[: index + 1])
            if value is not None
        ]
        for key, values in panel["macro"].items()
    }


def _point_in_time_market_history(panel: dict[str, Any], index: int) -> dict[str, list[dict[str, Any]]]:
    return {
        symbol.upper(): [
            {"date": panel["dates"][row_index], "close": value}
            for row_index, value in enumerate(values[: index + 1])
            if value is not None
        ]
        for symbol, values in panel["market"].items()
    }


def _point_in_time_context(
    panel: dict[str, Any],
    index: int,
    previous_score: float | None,
    previous_dimensions: dict[str, float] | None,
) -> dict[str, Any]:
    """Build the same context seam used by the live pipeline, using only rows through ``index``."""
    from pipeline.run import _build_risk_context

    macro = SimpleNamespace(payload=_macro_payload(panel, index))
    empty_dataset = SimpleNamespace(payload=SimpleNamespace(assets=[]))
    histories = _point_in_time_market_history(panel, index)
    return _build_risk_context(
        macro=macro,
        equities=empty_dataset,
        crypto=empty_dataset,
        commodities=empty_dataset,
        histories=histories,
        qualities=[1.0],
        prev_total_score=previous_score,
        prev_dim_scores=previous_dimensions,
        risk_history=[],
        series_history=_point_in_time_series_history(panel, index),
    )


def _path_identity(result: Any) -> dict[str, Any]:
    counts = {"percentile": 0, "heuristic_fallback": 0, "missing": 0}
    for dimension in result.dimensions:
        for indicator in dimension.indicators:
            if indicator.value is None:
                counts["missing"] += 1
            elif indicator.percentile is not None:
                counts["percentile"] += 1
            else:
                counts["heuristic_fallback"] += 1
    active = [key for key in ("percentile", "heuristic_fallback") if counts[key] > 0]
    if active == ["percentile"]:
        path = "production_percentile"
    elif active == ["heuristic_fallback"]:
        path = "heuristic_fallback"
    elif active:
        path = "production_mixed_percentile_heuristic"
    else:
        path = "no_observed_indicators"
    return {"scoring_path": path, "indicator_path_counts": counts}


def _forward_outcome(values: list[float | None], index: int, horizon: int) -> dict[str, Any] | None:
    window = values[index : index + horizon + 1]
    if len(window) != horizon + 1 or any(value is None for value in window):
        return None
    clean = [float(value) for value in window]
    base = clean[0]
    if base == 0:
        return None
    returns = [
        (clean[offset] - clean[offset - 1]) / clean[offset - 1]
        for offset in range(1, len(clean))
        if clean[offset - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    peak = clean[0]
    max_drawdown = 0.0
    for value in clean[1:]:
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    return {
        "max_drawdown": round(max_drawdown, 6),
        "realized_vol": round(math.sqrt(variance) * math.sqrt(252.0) * 100.0, 4),
        "observations": horizon,
    }


def _rank(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and ordered[end][1] == ordered[cursor][1]:
            end += 1
        average = (cursor + end - 1) / 2.0 + 1.0
        for position in range(cursor, end):
            ranks[ordered[position][0]] = average
        cursor = end
    return ranks


def _spearman(rows: list[dict[str, Any]], horizon: int) -> float | None:
    usable = [
        row for row in rows
        if row["outcomes"].get(str(horizon)) is not None
    ]
    if len(usable) < 3:
        return None
    scores = [float(row["total_score"]) for row in usable]
    losses = [-float(row["outcomes"][str(horizon)]["max_drawdown"]) for row in usable]
    score_ranks = _rank(scores)
    loss_ranks = _rank(losses)
    score_mean = sum(score_ranks) / len(score_ranks)
    loss_mean = sum(loss_ranks) / len(loss_ranks)
    numerator = sum(
        (a - score_mean) * (b - loss_mean)
        for a, b in zip(score_ranks, loss_ranks, strict=True)
    )
    denominator = math.sqrt(
        sum((value - score_mean) ** 2 for value in score_ranks)
        * sum((value - loss_mean) ** 2 for value in loss_ranks)
    )
    return round(numerator / denominator, 4) if denominator else None


def _event_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        row for row in rows
        if row["outcomes"].get(str(CALIBRATION_EVENT_HORIZON)) is not None
    ]
    if not usable:
        return {"evaluated": 0, "alerts": 0, "events": 0, "precision": None, "recall": None, "false_positive_rate": None}
    alerts = [row["total_score"] >= CALIBRATION_ALERT_SCORE for row in usable]
    events = [
        row["outcomes"][str(CALIBRATION_EVENT_HORIZON)]["max_drawdown"] <= CALIBRATION_EVENT_DRAWDOWN
        for row in usable
    ]
    true_positive = sum(alert and event for alert, event in zip(alerts, events, strict=True))
    false_positive = sum(alert and not event for alert, event in zip(alerts, events, strict=True))
    false_negative = sum(not alert and event for alert, event in zip(alerts, events, strict=True))
    true_negative = sum(not alert and not event for alert, event in zip(alerts, events, strict=True))
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else None
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else None
    false_positive_rate = false_positive / (false_positive + true_negative) if false_positive + true_negative else None
    return {
        "evaluated": len(usable),
        "alerts": sum(alerts),
        "events": sum(events),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "true_negative": true_negative,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "false_positive_rate": round(false_positive_rate, 4) if false_positive_rate is not None else None,
    }


def _lead_time_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    event_horizon = str(CALIBRATION_EVENT_HORIZON)
    event_flags = [
        row["outcomes"].get(event_horizon) is not None
        and row["outcomes"][event_horizon]["max_drawdown"] <= CALIBRATION_EVENT_DRAWDOWN
        for row in rows
    ]
    leads: list[int] = []
    event_index = 0
    while event_index < len(rows):
        if not event_flags[event_index] or (event_index > 0 and event_flags[event_index - 1]):
            event_index += 1
            continue
        alerts = [
            position for position in range(max(0, event_index - CALIBRATION_EVENT_HORIZON + 1), event_index + 1)
            if rows[position]["total_score"] >= CALIBRATION_ALERT_SCORE
        ]
        if alerts:
            leads.append(event_index - alerts[0])
        event_index += 1
    return {
        "event_onsets": sum(1 for index, flag in enumerate(event_flags) if flag and (index == 0 or not event_flags[index - 1])),
        "alerts_with_lead": len(leads),
        "lead_time_observations": leads,
        "median_lead_time_observations": round(sorted(leads)[len(leads) // 2], 2) if leads else None,
    }


def _stability_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"evaluated": 0, "level_switches": 0, "switches_per_100": None, "mean_abs_score_change": None}
    switches = sum(rows[index]["risk_level"] != rows[index - 1]["risk_level"] for index in range(1, len(rows)))
    changes = [
        abs(float(rows[index]["total_score"]) - float(rows[index - 1]["total_score"]))
        for index in range(1, len(rows))
    ]
    return {
        "evaluated": len(rows),
        "level_switches": switches,
        "switches_per_100": round(switches / len(rows) * 100.0, 4),
        "mean_abs_score_change": round(sum(changes) / len(changes), 4) if changes else 0.0,
    }


def _metrics_for_rows(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    usable = [row for row in rows if row["outcomes"].get(str(horizon)) is not None]
    return {
        "coverage": {
            "scored": len(rows),
            "outcome_available": len(usable),
            "outcome_ratio": round(len(usable) / len(rows), 4) if rows else 0.0,
        },
        "ranking": {"spearman_score_vs_forward_loss": _spearman(rows, horizon)},
        "event_discrimination": _event_metrics(rows),
        "lead_time": _lead_time_metrics(rows) if horizon == CALIBRATION_EVENT_HORIZON else None,
        "stability": _stability_metrics(rows),
    }


def _fingerprint(panel: dict[str, Any], model_config: dict[str, Any]) -> str:
    encoded = json.dumps({"panel": panel, "risk_model": model_config}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def replay_production_path(panel: dict[str, Any], settings: Any | None = None) -> dict[str, Any]:
    """Replay ``RiskModel.score`` in date order with a strictly point-in-time context.

    The returned artifact is JSON-safe and intentionally includes every observation's scoring
    path, evidence state, source/missing-data disclosure, and forward outcomes. It is suitable
    for deterministic CI fixtures as well as a manually fetched historical panel.
    """
    normalized = normalize_calibration_panel(panel)
    from pipeline.risk.model import RiskModel
    from pipeline.settings import Settings

    resolved_settings = settings or Settings()
    model_config = resolved_settings.load_risk_model()
    model = RiskModel(resolved_settings)
    dates = normalized["dates"]
    market_values = normalized["market"]["spy"]
    observations: list[dict[str, Any]] = []
    previous_score: float | None = None
    previous_dimensions: dict[str, float] | None = None
    for index, date_value in enumerate(dates):
        result = model.score(_point_in_time_context(normalized, index, previous_score, previous_dimensions))
        path = _path_identity(result)
        if normalized["evaluate"][index]:
            observations.append(
                {
                    "date": date_value,
                    "regime": normalized["regimes"][index],
                    "total_score": result.total_score,
                    "risk_level": result.risk_level,
                    "evidence_state": result.evidence_state,
                    "evidence_coverage": result.evidence_coverage,
                    "scoring_path": path["scoring_path"],
                    "indicator_path_counts": path["indicator_path_counts"],
                    "max_history_date": date_value,
                    "source_revision_policy": normalized["source_metadata"].get("revision_policy", "unspecified"),
                    "outcomes": {},
                }
            )
        previous_score = result.total_score
        previous_dimensions = {dimension.key: dimension.score for dimension in result.dimensions}
    date_to_index = {date_value: index for index, date_value in enumerate(dates)}
    for observation in observations:
        index = date_to_index[observation["date"]]
        observation["outcomes"] = {
            str(horizon): _forward_outcome(market_values, index, horizon)
            for horizon in PRODUCTION_CALIBRATION_HORIZONS
        }

    grouped = {
        "all": observations,
        "by_scoring_path": {
            path: [row for row in observations if row["scoring_path"] == path]
            for path in sorted({row["scoring_path"] for row in observations})
        },
        "by_regime": {
            regime: [row for row in observations if row["regime"] == regime]
            for regime in sorted({row["regime"] for row in observations if row["regime"] != "warmup"})
        },
    }
    metrics = {
        "horizons": {
            str(horizon): _metrics_for_rows(observations, horizon)
            for horizon in PRODUCTION_CALIBRATION_HORIZONS
        },
        "by_scoring_path": {
            path: {
                str(horizon): _metrics_for_rows(rows, horizon)
                for horizon in PRODUCTION_CALIBRATION_HORIZONS
            }
            for path, rows in grouped["by_scoring_path"].items()
        },
        "by_regime": {
            regime: {
                str(horizon): _metrics_for_rows(rows, horizon)
                for horizon in PRODUCTION_CALIBRATION_HORIZONS
            }
            for regime, rows in grouped["by_regime"].items()
        },
    }
    return {
        "artifact": "risk_calibration_production_path",
        "artifact_version": "1.0.0",
        "model_version": model.model_version,
        "input_fingerprint": _fingerprint(normalized, model_config),
        "point_in_time_policy": {
            "history_includes_rows_through_score_date": True,
            "future_observations_excluded_from_score": True,
            "warmup_rows_excluded_from_metrics": True,
        },
        "evaluation_policy": {
            "horizons": list(PRODUCTION_CALIBRATION_HORIZONS),
            "alert_score": CALIBRATION_ALERT_SCORE,
            "event_horizon": CALIBRATION_EVENT_HORIZON,
            "event_drawdown": CALIBRATION_EVENT_DRAWDOWN,
        },
        "source_metadata": normalized["source_metadata"],
        "missing_observations": normalized["missing_observations"],
        "path_counts": {
            path: len(rows) for path, rows in grouped["by_scoring_path"].items()
        },
        "regime_counts": {
            regime: len(rows) for regime, rows in grouped["by_regime"].items()
        },
        "metrics": metrics,
        "observations": observations,
    }
