"""Sub-indicator → 0-100 risk score mapping (architecture P0-5 methodology v1 + Fix rounds 5Y percentile primary path).

- Primary path (P0-2): indicator value → percentile and z_score against the 5Y history window
  (FRED/quote series) → mapped to a 0-100 risk score; percentile_window_years comes from
  config/risk_model.yaml.
- Fallback path: when history is insufficient (< min_history_samples), use the heuristic
  mapping table (HEURISTIC_RULES), guaranteeing a deterministic output in every scenario.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

# Heuristic mapping table: key → [(threshold, score)], interpolated by value ascending
HEURISTIC_RULES: dict[str, list[tuple[float, float]]] = {
    "vix": [(10, 5), (15, 20), (20, 40), (25, 60), (30, 75), (40, 90), (50, 98)],
    "hy_oas": [(2.0, 10), (3.0, 30), (4.0, 55), (5.0, 70), (6.0, 85), (8.0, 95)],
    "ig_oas": [(0.8, 10), (1.2, 30), (1.6, 50), (2.0, 70), (2.5, 85), (3.5, 95)],
    "dgs10": [(2.0, 40), (3.0, 45), (4.0, 50), (4.5, 60), (5.0, 70), (6.0, 85)],
    "real_rate_dfii10": [(0.0, 20), (0.5, 35), (1.0, 50), (1.5, 65), (2.0, 80), (2.5, 90)],
    "yield_curve_10y2y": [(-0.5, 95), (0.0, 75), (0.5, 55), (1.0, 40), (1.5, 30), (2.0, 25)],
    "dollar_index": [(95, 30), (100, 40), (105, 55), (110, 70), (115, 85)],
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

# Minimum number of history samples (below which fall back to the heuristic table; ≈ 3 months of daily data ≈ 60 samples)
MIN_HISTORY_SAMPLES = 60


def heuristic_risk_score(key: str, value: float | None) -> float | None:
    """Return a 0-100 risk score from the heuristic mapping table (linear interpolation, clamped at the bounds)."""
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
    """Filter invalid values (NaN/Infinity/None), returning a list of finite numbers."""
    out: list[float] = []
    for v in history:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)):
            out.append(float(v))
    return out


def percentile_rank(value: float, history: Sequence[float]) -> float:
    """Historical percentile (0-100): share of samples ≤ value.

    Uses the share of finite samples at or below the value.
    """
    hist = _finite_history(history)
    if not hist:
        return 50.0
    below = sum(1 for v in hist if v <= value)
    return below / len(hist) * 100.0


def z_score(value: float, history: Sequence[float]) -> float | None:
    """Historical z_score ((value - mean) / std); returns None when samples are too few or std≈0."""
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
    """Percentile → 0-100 risk score.

    - higher_is_riskier: percentile is the risk score (90th pct → 90).
    - lower_is_riskier: inverted (10th pct → 90).
    - neutral: the farther from the median the riskier (50th pct → 0, extremes → 100).
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
    """Sub-indicator → (risk_score, percentile, z_score) (P0-2 primary path).

    Prefers the 5Y historical percentile; falls back to the heuristic mapping table when history
    is insufficient, returning percentile/z_score=None.
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
