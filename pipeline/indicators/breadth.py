"""市场宽度指标（架构 §3.2 equity_structure；评审 P0-3 历史短板标注）。

MVP 用指数代理：SPY（大盘）、IWM（小盘）、SOXX（半导体）；
历史 2008-2012 宽度数据不可得 → 校准报告须标注近似重建（T05 落实）。
"""

from __future__ import annotations

from typing import Any

from pipeline.indicators.technical import closes_of


def breadth_above_ma200(history: dict[str, list[dict[str, Any]]], window: int = 200) -> float | None:
    """200 日均线上方比例（基于传入指数的收盘序列）。"""
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
    """新高/新低计数（近 N 日创新高/新低的资产数）。"""
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
    """target 相对 benchmark 的 N 日相对强弱（百分比）。"""
    t_values = closes_of(history.get(target, []))
    b_values = closes_of(history.get(benchmark, []))
    if len(t_values) <= lookback or len(b_values) <= lookback:
        return None
    t_ret = (t_values[-1] - t_values[-lookback - 1]) / t_values[-lookback - 1]
    b_ret = (b_values[-1] - b_values[-lookback - 1]) / b_values[-lookback - 1]
    return round((t_ret - b_ret) * 100.0, 4)


def breadth_snapshot(history: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """汇总宽度指标（含 is_proxy 标记：MVP 用指数代理）。"""
    hl = new_highs_lows(history)
    return {
        "breadth_above_ma200": breadth_above_ma200(history),
        "new_highs_ratio": hl["new_highs"],
        "new_lows_ratio": hl["new_lows"],
        "small_cap_relative": relative_strength(history, "IWM", "SPY"),
        "semis_relative": relative_strength(history, "SOXX", "SPY"),
        "is_proxy": True,
        "note": "MVP 宽度为指数代理（SPY/IWM/SOXX）；2008-2012 历史需近似重建（T05 校准报告标注）",
    }
