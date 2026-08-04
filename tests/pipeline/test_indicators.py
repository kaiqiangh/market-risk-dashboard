"""Indicators tests (technical/breadth/flow/trend)."""

from __future__ import annotations

import pytest

from pipeline.indicators import breadth, flow, technical, trend


def _rows(closes: list[float]) -> list[dict]:
    return [
        {"date": f"2026-01-{i + 1:02d}", "open": c, "high": c, "low": c, "close": c, "volume": 1000.0}
        for i, c in enumerate(closes)
    ]


def test_moving_average() -> None:
    assert technical.moving_average([1, 2, 3, 4, 5], 3) == 4.0
    assert technical.moving_average([1, 2], 3) is None


def test_rsi_extremes() -> None:
    up = list(range(1, 30))  # continuously rising → RSI 100
    assert technical.rsi(up, 14) == 100.0
    down = list(range(30, 1, -1))  # continuously falling → RSI 0
    rsi_down = technical.rsi(down, 14)
    assert rsi_down is not None and rsi_down < 5


def test_distance_from_ma() -> None:
    values = [100] * 50 + [110]  # latest above MA50
    dist = technical.distance_from_ma(values, 50)
    assert dist is not None and dist > 0


def test_drawdown_and_momentum() -> None:
    values = [100, 110, 120, 90]  # high 120 → latest 90
    dd = technical.drawdown_52w(values)
    assert dd is not None and dd < 0
    mom = technical.momentum([100] * 63 + [110], 63)
    assert mom is not None and mom > 0


def test_technical_snapshot() -> None:
    closes = [float(i) for i in range(1, 220)]
    snap = technical.technical_snapshot(_rows(closes))
    assert snap["ma200"] is not None
    assert snap["rsi14"] is not None
    assert 0 <= snap["percentile_5y"] <= 100


def test_breadth_snapshot() -> None:
    spy = _rows([100.0] * 200 + [110.0])
    iwm = _rows([100.0] * 200 + [95.0])
    soxx = _rows([100.0] * 200 + [120.0])
    snap = breadth.breadth_snapshot({"SPY": spy, "IWM": iwm, "SOXX": soxx})
    assert snap["breadth_above_ma200"] == round(2 / 3, 4)  # SPY/SOXX above MA200, IWM below
    assert snap["is_proxy"] is True
    assert snap["small_cap_relative"] is not None


def test_flow_snapshot() -> None:
    rows = _rows([100.0] * 30)
    rows[-1]["volume"] = 5000.0  # volume spike
    snap = flow.flow_snapshot(rows)
    assert snap["obv"] is not None
    assert snap["mfi"] is not None
    assert snap["relative_volume"] is not None
    assert snap["is_proxy"] is True


def test_trend_snapshot() -> None:
    spy = _rows([100.0] * 200 + [120.0])
    snap = trend.trend_snapshot({"SPY": spy}, "SPY")
    assert snap["price_vs_ma200"] is not None
    assert snap["drawdown_52w"] is not None
    assert snap["last_close"] == 120.0


# ---------- #69: breadth discloses its sample ----------

def _breadth_history(considered: int) -> dict[str, list[dict]]:
    """A history dict with `considered` series long enough to qualify; all but the last four
    close above their 200-day MA (the last four make new 63-day lows)."""
    rows: dict[str, list[dict]] = {}
    for i in range(considered):
        symbol = f"SYM{i:02d}"
        above = i < considered - 4  # all but the last four close above the MA
        close = 110.0 if above else 90.0
        # 260 rows so every series clears the 200-day MA window and the 64-day lookback.
        rows[symbol] = [
            {"date": f"2025-01-{d % 28 + 1:02d}", "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}
            for d in range(260)
        ] + [
            {"date": "2026-08-03", "open": close, "high": close, "low": close, "close": close}
        ]
    return rows


def test_breadth_publishes_qualifying_and_considered() -> None:
    """#69: breadth_snapshot publishes qualifying + considered counts alongside the ratio."""
    from pipeline.indicators.breadth import breadth_snapshot

    snap = breadth_snapshot(_breadth_history(18))
    assert "breadth_qualifying" in snap
    assert "breadth_considered" in snap
    assert snap["breadth_considered"] == 18
    assert snap["breadth_qualifying"] == 14
    assert snap["breadth_above_ma200"] == pytest.approx(14 / 18, abs=1e-4)
    assert snap["new_considered"] == 18
    # The four below-MA series close at a 63-day low; the rest make new highs.
    assert snap["new_highs_qualifying"] == 14
    assert snap["new_lows_qualifying"] == 4


def test_thin_breadth_sample_is_visible() -> None:
    """#69: a 4-of-18 sample is distinguishable from an 18-of-18 sample in the output."""
    from pipeline.indicators.breadth import breadth_snapshot

    thin = breadth_snapshot(_breadth_history(4))
    full = breadth_snapshot(_breadth_history(18))
    # Same ratio, different basis — the counts make the thinning visible.
    assert thin["breadth_qualifying"] < full["breadth_qualifying"]
    assert thin["breadth_considered"] < full["breadth_considered"]
    assert thin["breadth_considered"] == 4
