"""Risk model tests (scoring/model/regime/confidence)."""

from __future__ import annotations

from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.model import RiskModel
from pipeline.risk.scoring import (
    compute_indicator_score,
    heuristic_risk_score,
    percentile_rank,
    percentile_risk_score,
    z_score,
)
from pipeline.schemas import MacroDataset, MacroIndicator, RiskModelResult


def test_heuristic_risk_score_bounds() -> None:
    assert heuristic_risk_score("vix", 15) == 20.0
    assert heuristic_risk_score("vix", 10) == 5.0
    assert heuristic_risk_score("vix", 100) == 98.0  # clamped at bounds
    assert heuristic_risk_score("vix", None) is None
    assert heuristic_risk_score("unknown_key", 10) is None


def test_percentile_risk_score() -> None:
    history = list(range(1, 101))  # 1..100
    assert percentile_risk_score(100, history, "higher_is_riskier") == 100.0
    assert percentile_risk_score(1, history, "higher_is_riskier") < 5
    # lower_is_riskier inverted
    low = percentile_risk_score(1, history, "lower_is_riskier")
    assert low > 95


def test_percentile_rank_and_zscore() -> None:
    history = list(range(1, 101))
    assert percentile_rank(50, history) == 50.0
    assert percentile_rank(100, history) == 100.0
    z = z_score(50, history)
    assert z is not None and abs(z) < 0.2
    assert z_score(50, []) is None  # too few samples


def test_compute_indicator_score_percentile_primary() -> None:
    """P0-2: with sufficient history the percentile is the primary path; percentile/z_score are non-None."""
    history = list(range(1, 101))
    score, pct, z = compute_indicator_score("vix", 90, history, "higher_is_riskier")
    assert pct == 90.0
    assert z is not None
    assert score == 90.0  # 90th pct → 90 points
    # lower_is_riskier inverted
    score2, pct2, _ = compute_indicator_score("breadth_above_ma200", 10, history, "lower_is_riskier")
    assert pct2 == 10.0
    assert score2 == 90.0


def test_compute_indicator_score_heuristic_fallback() -> None:
    """Insufficient history (<60 samples) → heuristic table fallback, percentile/z_score=None."""
    short_history = list(range(1, 10))
    score, pct, z = compute_indicator_score("vix", 25, short_history, "higher_is_riskier")
    assert pct is None
    assert z is None
    assert score == 60.0  # heuristic vix 25 → 60
    # no history
    score2, pct2, z2 = compute_indicator_score("vix", 25, None, "higher_is_riskier")
    assert pct2 is None and z2 is None and score2 == 60.0


def test_regime_crisis_on_vix_40() -> None:
    regime, evidence = regime_mod.infer_regime({"vix": 45.0, "hy_oas": 3.0})
    assert regime == "crisis"
    assert evidence


def test_regime_goldilocks() -> None:
    # low vol + positive momentum + healthy breadth + non-extreme curve → goldilocks
    regime, _ = regime_mod.infer_regime({"vix": 12.0, "hy_oas": 2.5, "yield_curve_10y2y": 0.3, "breadth_above_ma200": 0.7, "momentum_3m": 8.0})
    assert regime in ("goldilocks", "risk_on")


def _synthetic_context() -> dict:
    macro = MacroDataset(
        rates=[
            MacroIndicator(key="dgs10", label="10Y", value=4.2, unit="pct", source="FRED"),
            MacroIndicator(key="dgs2", label="2Y", value=3.8, unit="pct", source="FRED"),
            MacroIndicator(key="dfii10", label="Real", value=1.9, unit="pct", source="FRED"),
            MacroIndicator(key="vixcls", label="VIX", value=25.0, unit="index", source="FRED"),
        ],
        credit=[MacroIndicator(key="bamlh0a0hym2", label="HY", value=4.5, unit="pct", source="FRED")],
        fx=[],
    )
    return {
        "macro": macro,
        "breadth": {"breadth_above_ma200": 0.55, "new_highs_ratio": 0.4, "new_lows_ratio": 0.2,
                    "small_cap_relative": -1.0, "semis_relative": 2.0},
        "trend": {"price_vs_ma200": 8.0, "drawdown_52w": -5.0, "momentum_3m": 3.0, "realized_vol": 18.0},
        "cross_asset": {"confirmation": 0.6},
        "data_quality": 0.9,
        "_prev_total_score": 50.0,
    }


def test_risk_model_produces_valid_result() -> None:
    model = RiskModel()
    result = model.score(_synthetic_context())
    assert isinstance(result, RiskModelResult)
    assert 0 <= result.total_score <= 100
    assert 0 <= result.confidence <= 1
    assert len(result.dimensions) == 6
    assert result.top_drivers  # has top drivers
    assert "definitive probability" not in result.disclaimer or "modeled estimate" in result.disclaimer


def test_risk_model_trend_1d() -> None:
    model = RiskModel()
    result = model.score(_synthetic_context())
    assert result.trend_1d is not None


def test_risk_model_percentile_with_series_history() -> None:
    """P0-2: after series_history injection percentile/z_score are non-None, the risk score uses the percentile path."""
    ctx = _synthetic_context()
    # 5Y daily-frequency window (VIX 25 sits high in the history)
    history = [10.0 + (i % 20) for i in range(1300)]  # 10~29 cycle
    ctx["series_history"] = {"vixcls": [{"date": f"2021-{i:02d}-01", "value": v} for i, v in enumerate(history)]}
    model = RiskModel()
    result = model.score(ctx)
    vix_ind = next(
        ind for dim in result.dimensions if dim.key == "volatility"
        for ind in dim.indicators if ind.key == "vix"
    )
    assert vix_ind.percentile is not None
    assert vix_ind.z_score is not None
    # 25 in the uniform 10~29 history has percentile ≈ 76 (share of samples ≤ 25)
    assert 65 <= vix_ind.percentile <= 85


def test_risk_model_dimension_trend_computed() -> None:
    """P2-11: after _prev_dim_scores injection the dimension trend is not always flat and the direction is correct."""
    ctx = _synthetic_context()
    ctx["_prev_dim_scores"] = {
        "macro": 90.0, "liquidity_credit": 20.0, "equity_structure": 20.0,
        "volatility": 20.0, "cross_asset": 50.0, "trend": 40.0,
    }
    result = RiskModel().score(ctx)
    by_key = {d.key: d for d in result.dimensions}
    # macro current score (≈62) is far below yesterday's 90 → falling
    assert by_key["macro"].trend == "falling"
    # equity_structure current score (≈47) is above yesterday's 20 → rising
    assert by_key["equity_structure"].trend == "rising"
    # at least one dimension is not flat (scores actually changed)
    assert any(d.trend != "flat" for d in result.dimensions)


def test_risk_model_trend_1w_1m_from_history() -> None:
    """P2-11: after _risk_history injection trend_1w/trend_1m are computable."""
    ctx = _synthetic_context()
    rows = [
        {"date": f"2026-06-{i:02d}", "total_score": 30.0 + (i % 3)}
        for i in range(1, 25)
    ]
    ctx["_risk_history"] = rows
    ctx["_prev_total_score"] = rows[-1]["total_score"]
    result = RiskModel().score(ctx)
    assert result.trend_1w is not None
    assert result.trend_1m is not None


def test_risk_model_level_thresholds() -> None:
    model = RiskModel()
    # low-risk context → score should be lower than the high-VIX context
    low_ctx = _synthetic_context()
    low_ctx["macro"].rates = [MacroIndicator(key="vixcls", label="VIX", value=12.0, unit="index", source="FRED")]
    low = model.score(low_ctx)
    high_ctx = _synthetic_context()
    high_ctx["macro"].rates = [MacroIndicator(key="vixcls", label="VIX", value=45.0, unit="index", source="FRED")]
    high = model.score(high_ctx)
    assert high.total_score > low.total_score


def test_confidence_consistency() -> None:
    assert conf_mod.compute_confidence(1.0, 1.0, 1.0) == 1.0
    assert conf_mod.compute_confidence(0.5, 0.5, 0.5) == 0.5
    assert conf_mod.consistency_from_dimension_scores([20, 20, 20]) == 1.0
    assert conf_mod.consistency_from_dimension_scores([0, 100]) < 0.5

