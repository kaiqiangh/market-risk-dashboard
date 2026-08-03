"""Indicators tests (technical/breadth/flow/trend)."""

from __future__ import annotations

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
