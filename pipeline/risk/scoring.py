"""子指标 → 0-100 风险分映射（架构 P0-5 方法论 v1 + Fix 轮次 5Y 百分位主路径）。

- 主路径（P0-2）：指标值 → 对照 5Y 历史窗口（FRED/行情序列）计算百分位与 z_score
  → 映射 0-100 风险分；percentile_window_years 来自 config/risk_model.yaml。
- 回退路径：历史数据不足（< min_history_samples）时使用启发式映射表
  （HEURISTIC_RULES），保证任何场景都有确定性输出。
"""

from __future__ import annotations

import math
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

# 历史窗口最短样本数（低于则回退启发式表；约 3 个月日频 ≈ 60 样本）
MIN_HISTORY_SAMPLES = 60


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


def _finite_history(history: Sequence[float]) -> list[float]:
    """过滤非法值（NaN/Infinity/None），返回有限数值列表。"""
    out: list[float] = []
    for v in history:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)):
            out.append(float(v))
    return out


def percentile_rank(value: float, history: Sequence[float]) -> float:
    """历史百分位（0-100）：小于等于 value 的样本占比。

    与 percentile_risk_score 的语义一致（<= 计数 / 总数）。
    """
    hist = _finite_history(history)
    if not hist:
        return 50.0
    below = sum(1 for v in hist if v <= value)
    return below / len(hist) * 100.0


def z_score(value: float, history: Sequence[float]) -> float | None:
    """历史 z_score（(value - mean) / std）；样本过少或 std≈0 时返回 None。"""
    hist = _finite_history(history)
    if len(hist) < 2:
        return None
    mean = sum(hist) / len(hist)
    var = sum((v - mean) ** 2 for v in hist) / (len(hist) - 1)
    std = math.sqrt(var)
    if std < 1e-12:
        return None
    return (value - mean) / std


def percentile_to_risk(pct: float, direction: str) -> float:
    """百分位 → 0-100 风险分。

    - higher_is_riskier：百分位即风险分（90 分位 → 90 分）。
    - lower_is_riskier：反向（10 分位 → 90 分）。
    - neutral：距中位数越远越危险（50 分位 → 0 分，极值 → 100 分）。
    """
    pct = max(0.0, min(100.0, pct))
    if direction == "lower_is_riskier":
        return round(100.0 - pct, 2)
    if direction == "neutral":
        return round(abs(pct - 50.0) * 2.0, 2)
    return round(pct, 2)


def compute_indicator_score(
    key: str,
    value: float | None,
    history: Sequence[float] | None,
    direction: str = "higher_is_riskier",
    fallback: float = 50.0,
    min_samples: int = MIN_HISTORY_SAMPLES,
) -> tuple[float, float | None, float | None]:
    """子指标 → (risk_score, percentile, z_score)（P0-2 主路径）。

    优先 5Y 历史百分位；历史不足时回退启发式映射表，并返回 percentile/z_score=None。
    """
    if value is None:
        return fallback, None, None
    hist = _finite_history(history or [])
    if len(hist) >= min_samples:
        pct = percentile_rank(value, hist)
        z = z_score(value, hist)
        return percentile_to_risk(pct, direction), round(pct, 2), (round(z, 4) if z is not None else None)
    score = heuristic_risk_score(key, value)
    return (score if score is not None else fallback), None, None


def percentile_risk_score(
    value: float | None,
    history: Sequence[float],
    direction: str = "higher_is_riskier",
    fallback: float = 50.0,
) -> float | None:
    """历史百分位 → 风险分（0-100）。higher_is_riskier：百分位即风险分。

    兼容旧接口：无历史时返回 fallback。
    """
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
