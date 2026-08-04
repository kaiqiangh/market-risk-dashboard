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
    assert 0 <= snap["percentile_1y"] <= 100
    assert snap["percentile_1y_obs"] > 0


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


# ---------- #70: windows and labels describe what they actually measure ----------

def test_percentile_field_reports_its_window() -> None:
    """#70: the percentile field's name states the window it actually uses (1y history)."""
    closes = [float(i) for i in range(1, 260)]  # ~1y of daily closes
    snap = technical.technical_snapshot(_rows(closes))
    assert "percentile_1y" in snap, "the percentile field must state its window (1y)"
    assert "percentile_5y" not in snap, "the overclaiming 5y name must be gone"
    assert 0 <= snap["percentile_1y"] <= 100


def test_percentile_publishes_observation_count() -> None:
    """#70: a percentile is published with the number of observations behind it; a thin
    sample (30 points) is distinguishable from a full one (250 points)."""
    thin = technical.technical_snapshot(_rows([float(i) for i in range(1, 32)]))
    full = technical.technical_snapshot(_rows([float(i) for i in range(1, 252)]))
    assert thin["percentile_1y_obs"] < full["percentile_1y_obs"]
    assert thin["percentile_1y_obs"] == 30
    assert full["percentile_1y_obs"] == 250


def test_drawdown_uses_trailing_52w_high() -> None:
    """#70: drawdown_52w measures against the trailing 52-week high, not the series max."""
    # Old peak 200 sits BEFORE the trailing 52-week window (260 flat + 20 flat closes).
    values = [200.0] + [100.0] * 260 + [110.0] * 20
    dd = technical.drawdown_52w(values)
    assert dd == 0.0, f"trailing 52w high is 110, latest is 110 -> no drawdown, got {dd}"
    # The series max (200) would claim -45%; the trailing window must not see it.
    assert dd > -50.0


def test_macro_lookback_boundary() -> None:
    """#70: `_change(rows, lookback)` spans exactly `lookback` periods, consistent with
    `momentum`'s lookback semantics (change over `lookback` periods, not one fewer)."""
    from pipeline.collectors.macro import _change

    # 25 values, lookback 21 -> base is 21 periods before the latest.
    rows = [{"value": float(i)} for i in range(25)]
    assert _change(rows, 21) == 24.0 - 3.0  # v[24] - v[3]

    # A series shorter than the lookback spans the whole series (clamp at the oldest).
    short = [{"value": float(i)} for i in range(10)]
    assert _change(short, 21) == 9.0 - 0.0

    # The lookback must NOT include the extra (closer) period.
    assert _change(rows, 21) != 24.0 - 4.0
