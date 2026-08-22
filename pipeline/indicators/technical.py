"""Technical indicator computation (architecture §3.7 IndicatorEngine.technical).

Input history rows ([{date, open, high, low, close, volume}]), output an indicator dict.
All functions are pure computation with no IO; NaN/Infinity are always dropped.
"""

from __future__ import annotations

import math
from typing import Any, Sequence


def closes_of(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r["close"]) for r in rows if isinstance(r.get("close"), (int, float))]


def moving_average(values: Sequence[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return round(sum(values[-window:]) / window, 6)


def distance_from_ma(values: Sequence[float], window: int) -> float | None:
    """Percentage deviation of the latest close from the moving average (e.g. 4.1 = 4.1% above MA50)."""
    ma = moving_average(values, window)
    if ma is None or ma == 0 or not values:
        return None
    return round((values[-1] - ma) / ma * 100.0, 4)


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Wilder RSI(14), output 0-100."""
    if len(values) < period + 1:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    avg_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    avg_loss = sum(max(-change, 0.0) for change in changes[:period]) / period
    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 4)


def drawdown_52w(values: Sequence[float], window: int = 252) -> float | None:
    """52-week high drawdown, measured against the TRAILING 52-week high (#70).

    0 = no drawdown; -12.5 = -12.5% from the trailing 52-week high. A peak older than the
    trailing window is history, not the reference — the longer the series, the more wrong
    ``max(values)`` would be.
    """
    if not values:
        return None
    high = max(values[-window:])
    if high == 0:
        return None
    return round((values[-1] - high) / high * 100.0, 4)


def momentum(values: Sequence[float], lookback: int = 63) -> float | None:
    """N-trading-day momentum (percentage). lookback≈63 = 3 months."""
    if len(values) <= lookback or values[-lookback - 1] == 0:
        return None
    return round((values[-1] - values[-lookback - 1]) / values[-lookback - 1] * 100.0, 4)


def realized_vol(values: Sequence[float], window: int = 20, annualize: bool = True) -> float | None:
    """Realized volatility (std dev of daily returns; ×√252 annualized percentage when annualize=True)."""
    if len(values) < window + 1:
        return None
    returns = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(len(values) - window, len(values))
        if values[i - 1] != 0 and not math.isnan(values[i - 1])
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if annualize:
        std *= math.sqrt(252)
    return round(std * 100.0, 4)


def percentile_in_window(values: Sequence[float]) -> tuple[float | None, int]:
    """Percentile of the latest value within the window (0-100) + the observation count (#70).

    The second element is how many observations the rank is computed over, so a thin sample
    (30 points) is published differently from a full one (250 points).
    """
    if not values:
        return None, 0
    last = values[-1]
    window = values[:-1] or [last]
    below = sum(1 for v in window if v <= last)
    return round(below / len(window) * 100.0, 2), len(window)


def technical_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Output all basic technical indicators for a history segment."""
    values = closes_of(rows)
    percentile, percentile_obs = percentile_in_window(values)
    return {
        "ma20": moving_average(values, 20),
        "ma50": moving_average(values, 50),
        "ma200": moving_average(values, 200),
        "ma50_distance_pct": distance_from_ma(values, 50),
        "ma200_distance_pct": distance_from_ma(values, 200),
        "rsi14": rsi(values, 14),
        "drawdown_52w": drawdown_52w(values),
        "momentum_3m": momentum(values, 63),
        "realized_vol": realized_vol(values, 20),
        # #70: the field states the window actually used (1y history) and how many
        # observations back it.
        "percentile_1y": percentile,
        "percentile_1y_obs": percentile_obs,
    }
