"""Fund flow proxy indicators (architecture §3.2 flow; review P1-2 pseudo-precision risk).

Free sources have no tick/Level-2 data → MVP only provides proxy indicators (OBV/MFI/relative volume);
all estimates must carry the Estimated/Proxy marker.
"""

from __future__ import annotations

import math
from typing import Any


def obv(rows: list[dict[str, Any]]) -> float | None:
    """On-Balance Volume (latest value)."""
    obv_value = 0.0
    for i in range(1, len(rows)):
        close_prev = rows[i - 1].get("close")
        close = rows[i].get("close")
        volume = rows[i].get("volume")
        if not all(isinstance(v, (int, float)) for v in (close_prev, close, volume)):
            continue
        if close > close_prev:
            obv_value += float(volume)
        elif close < close_prev:
            obv_value -= float(volume)
    return round(obv_value, 2) if rows else None


def mfi(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    """Money Flow Index 0-100。"""
    if len(rows) < period + 1:
        return None
    pos_flow = 0.0
    neg_flow = 0.0
    for i in range(len(rows) - period, len(rows)):
        typical = _typical(rows[i])
        typical_prev = _typical(rows[i - 1])
        volume = rows[i].get("volume")
        if typical is None or typical_prev is None or not isinstance(volume, (int, float)):
            continue
        money_flow = typical * float(volume)
        if typical > typical_prev:
            pos_flow += money_flow
        elif typical < typical_prev:
            neg_flow += money_flow
    if neg_flow == 0:
        return 100.0
    ratio = pos_flow / neg_flow
    return round(100.0 - 100.0 / (1.0 + ratio), 4)


def relative_volume(rows: list[dict[str, Any]], window: int = 20) -> float | None:
    """Latest volume / average volume of the previous N days."""
    volumes = [float(r["volume"]) for r in rows if isinstance(r.get("volume"), (int, float))]
    if len(volumes) < window + 1:
        return None
    avg = sum(volumes[-window - 1 : -1]) / window
    if avg == 0:
        return None
    return round(volumes[-1] / avg, 4)


def flow_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "obv": obv(rows),
        "mfi": mfi(rows),
        "relative_volume": relative_volume(rows),
        "is_proxy": True,
        "note": "MVP fund flow uses proxy indicators (OBV/MFI/relative volume), not tick data (review P1-2)",
    }


def _typical(row: dict[str, Any]) -> float | None:
    high, low, close = row.get("high"), row.get("low"), row.get("close")
    if not all(isinstance(v, (int, float)) for v in (high, low, close)):
        return None
    return (float(high) + float(low) + float(close)) / 3.0
