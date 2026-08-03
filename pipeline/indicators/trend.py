"""Trend dimension indicators (architecture §3.2 trend).

Based on price vs moving averages/drawdown/momentum, output for the risk.trend dimension.
"""

from __future__ import annotations

from typing import Any

from pipeline.indicators.technical import (
    closes_of,
    distance_from_ma,
    drawdown_52w,
    momentum,
    moving_average,
)


def trend_snapshot(history: dict[str, list[dict[str, Any]]], benchmark: str = "SPY") -> dict[str, Any]:
    """Summarize trend indicators (benchmark index first; fall back to any asset when missing)."""
    rows = history.get(benchmark) or next(iter(history.values()), [])
    values = closes_of(rows)
    return {
        "price_vs_ma50": distance_from_ma(values, 50),
        "price_vs_ma200": distance_from_ma(values, 200),
        "drawdown_52w": drawdown_52w(values),
        "momentum_3m": momentum(values, 63),
        "ma50": moving_average(values, 50),
        "ma200": moving_average(values, 200),
        "last_close": values[-1] if values else None,
        "benchmark": benchmark,
    }
