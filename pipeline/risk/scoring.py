"""子指标 → 0-100 风险分映射（架构 P0-5 方法论 v1）。

MVP 采用确定性启发式映射表（可配置、可回测）；5Y 历史百分位窗口作为
percentile_score 辅助（equities 有历史时使用）。T05 校准报告验证口径。
"""

from __future__ import annotations

from typing import Any, Sequence

# 启发式映射表：key → [(threshold, score)]，按 value 从小到大插值
HEURISTIC_RULES: dict[str, list[tuple[float, float]]] = {
    "vix": [(10, 5), (15, 20), (20, 40), (25, 60), (30, 75), (40, 90), (50, 98)],
    "hy_oas": [(2.0, 10), (3.0, 30), (4.0, 55), (5.0, 70), (6.0, 85), (8.0, 95)],
    "ig_oas": [(0.8, 10), (1.2, 30), (1.6, 50), (2.0, 70), (2.5, 85), (3.5, 95)],
    "dgs10": [(2.0, 40), (3.0, 45), (4.0, 50), (4.5, 60), (5.0, 70), (6.0, 85)],
    "real_rate_dfii10": [(0.0, 20), (0.5, 35), (1.0, 50), (1.5, 65), (2.0, 80), (2.5, 90)],
    "yield_curve_10y2y": [(-0.5, 95), (0.0, 75), (0.5, 55), (1.0, 40), (1.5, 30), (2.0, 25)],
    "dxy": [(95, 30), (100, 40), (105, 55), (110, 70), (115, 85)],
    "breadth_above_ma200": [(0.2, 95), (0.4, 75), (0.5, 60), (0.6, 45), (0.7, 30), (0.85, 15)],
    "new_highs_ratio": [(0.0, 90), (0.1, 70), (0.3, 50), (0.5, 35), (0.7, 20), (0.9, 10)],
    "new_lows_ratio": [(0.0, 5), (0.1, 25), (0.3, 50), (0.5, 70), (0.7, 85), (0.9, 95)],
    "price_vs_ma200": [(-25, 95), (-10, 75), (0, 55), (10, 40), (20, 25), (35, 15)],
    "drawdown_52w": [(-40, 98), (-25, 88), (-15, 75), (-8, 60), (-3, 45), (0, 30), (5, 20)],
    "momentum_3m": [(-30, 95), (-15, 80), (-5, 65), (0, 55), (10, 40), (20, 25), (40, 10)],
    "realized_vol": [(10, 10), (15, 30), (20, 50), (30, 70), (40, 85), (60, 95)],
    "mfi": [(20, 90), (30, 70), (50, 50), (70, 30), (80, 15)],
    "rsi14": [(20, 80), (30, 65), (45, 50), (60, 35), (75, 25), (90, 15)],
}


def heuristic_risk_score(key: str, value: float | None) -> float | None:
    """按启发式映射表返回 0-100 风险分（线性插值，越界钳制）。"""
    if value is None:
        return None
    rules = HEURISTIC_RULES.get(key)
    if not rules:
        return None
    points = sorted(rules)
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            return round(y0 + (y1 - y0) * (value - x0) / (x1 - x0), 2)
    return None


def percentile_risk_score(
    value: float | None,
    history: Sequence[float],
    direction: str = "higher_is_riskier",
    fallback: float = 50.0,
) -> float | None:
    """历史百分位 → 风险分（0-100）。higher_is_riskier：百分位即风险分。"""
    if value is None:
        return None
    if not history:
        return fallback
    below = sum(1 for v in history if v <= value)
    pct = below / len(history) * 100.0
    if direction == "lower_is_riskier":
        return round(100.0 - pct, 2)
    return round(pct, 2)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
