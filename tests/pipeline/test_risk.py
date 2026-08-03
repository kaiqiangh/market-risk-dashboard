"""Risk 模型测试（scoring/model/regime/confidence）。"""

from __future__ import annotations

from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.model import RiskModel
from pipeline.risk.scoring import heuristic_risk_score, percentile_risk_score
from pipeline.schemas import MacroDataset, MacroIndicator, RiskModelResult


def test_heuristic_risk_score_bounds() -> None:
    assert heuristic_risk_score("vix", 15) == 20.0
    assert heuristic_risk_score("vix", 10) == 5.0
    assert heuristic_risk_score("vix", 100) == 98.0  # 越界钳制
    assert heuristic_risk_score("vix", None) is None
    assert heuristic_risk_score("unknown_key", 10) is None


def test_percentile_risk_score() -> None:
    history = list(range(1, 101))  # 1..100
    assert percentile_risk_score(100, history, "higher_is_riskier") == 100.0
    assert percentile_risk_score(1, history, "higher_is_riskier") < 5
    # lower_is_riskier 反转
    low = percentile_risk_score(1, history, "lower_is_riskier")
    assert low > 95


def test_regime_crisis_on_vix_40() -> None:
    regime, evidence = regime_mod.infer_regime({"vix": 45.0, "hy_oas": 3.0})
    assert regime == "crisis"
    assert evidence


def test_regime_goldilocks() -> None:
    # 低波动 + 正动量 + 宽度健康 + 曲线不极端 → goldilocks
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
    assert result.top_drivers  # 有 Top drivers
    assert "精确" not in result.disclaimer or "模型化" in result.disclaimer


def test_risk_model_trend_1d() -> None:
    model = RiskModel()
    result = model.score(_synthetic_context())
    assert result.trend_1d is not None


def test_risk_model_level_thresholds() -> None:
    model = RiskModel()
    # 低风险上下文 → 分数应低于高 VIX 上下文
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
