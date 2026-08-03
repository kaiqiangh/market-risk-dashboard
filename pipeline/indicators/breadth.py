"""Market breadth indicators (architecture §3.2 equity_structure; review P0-3 historical shortfall annotation).

MVP uses index proxies: SPY (large cap), IWM (small cap), SOXX (semiconductors);
breadth data for 2008-2012 history is unavailable → the calibration report must annotate
approximate reconstruction (implemented in T05).
"""

from __future__ import annotations

from typing import Any

from pipeline.indicators.technical import closes_of


def breadth_above_ma200(history: dict[str, list[dict[str, Any]]], window: int = 200) -> float | None:
    """Share of closes above the 200-day moving average (based on the passed-in index close series)."""
    above = 0
    total = 0
    for symbol, rows in history.items():
        values = closes_of(rows)
        if len(values) < window:
            continue
        ma = sum(values[-window:]) / window
        if ma == 0:
            continue
        above += 1 if values[-1] > ma else 0
        total += 1
    if total == 0:
        return None
    return round(above / total, 4)


def new_highs_lows(history: dict[str, list[dict[str, Any]]], lookback: int = 63) -> dict[str, float]:
    """New highs/lows counts (assets making new highs/lows in the last N days)."""
    highs = 0
    lows = 0
    total = 0
    for symbol, rows in history.items():
        values = closes_of(rows)
        if len(values) < lookback + 1:
            continue
        window = values[-lookback - 1 : -1]
        highs += 1 if values[-1] >= max(window) else 0
        lows += 1 if values[-1] <= min(window) else 0
        total += 1
    if total == 0:
        return {"new_highs": 0, "new_lows": 0, "total": 0}
    return {
        "new_highs": round(highs / total, 4),
        "new_lows": round(lows / total, 4),
        "total": total,
    }


def relative_strength(history: dict[str, list[dict[str, Any]]], target: str, benchmark: str = "SPY", lookback: int = 63) -> float | None:
    """N-day relative strength of target vs benchmark (percentage)."""
    t_values = closes_of(history.get(target, []))
    b_values = closes_of(history.get(benchmark, []))
    if len(t_values) <= lookback or len(b_values) <= lookback:
        return None
    t_ret = (t_values[-1] - t_values[-lookback - 1]) / t_values[-lookback - 1]
    b_ret = (b_values[-1] - b_values[-lookback - 1]) / b_values[-lookback - 1]
    return round((t_ret - b_ret) * 100.0, 4)


def breadth_snapshot(history: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Summarize breadth indicators (including the is_proxy marker: MVP uses index proxies)."""
    hl = new_highs_lows(history)
    return {
        "breadth_above_ma200": breadth_above_ma200(history),
        "new_highs_ratio": hl["new_highs"],
        "new_lows_ratio": hl["new_lows"],
        "small_cap_relative": relative_strength(history, "IWM", "SPY"),
        "semis_relative": relative_strength(history, "SOXX", "SPY"),
        "is_proxy": True,
        "note": "MVP breadth uses index proxies (SPY/IWM/SOXX); 2008-2012 history requires approximate reconstruction (noted in the T05 calibration report)",
    }
