"""Offline calibration engine (architecture §1.8 frozen: 2008/2018/2020 three segments).

All data is freely available: FRED VIXCLS/BAMLH0A0HYM2/DGS10 + yfinance SPX history.
Evaluation metrics (PRD §15 subset): early-warning lead time, risk score change speed,
maximum drawdown, future 5/10/20/30-day volatility, risk level stability.
Calibration red line: before calibration completes, the UI must not call the risk score
an "exact crash probability".
"""

from __future__ import annotations

from typing import Any

from pipeline.risk.scoring import heuristic_risk_score

CALIBRATION_WINDOWS = {
    "2008": {"start": "2008-08-01", "end": "2009-03-31", "note": "2008 financial crisis"},
    "2018": {"start": "2018-09-01", "end": "2018-12-31", "note": "2018 Q4 selloff"},
    "2020": {"start": "2020-02-01", "end": "2020-04-30", "note": "COVID crash"},
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

    # Early warning: days from the peak when the risk score first reaches ≥ 60 (negative = warned before the peak)
    early_warning_days: int | None = None
    for i, s in enumerate(scores):
        if s >= 60:
            early_warning_days = i - peak_idx
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
