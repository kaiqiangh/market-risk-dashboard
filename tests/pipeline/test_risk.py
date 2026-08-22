"""Risk model tests (scoring/model/regime/confidence)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.risk import confidence as conf_mod
from pipeline.risk import regime as regime_mod
from pipeline.risk.model import RiskModel
from pipeline.risk.model import _parse_thresholds
from pipeline.risk.scoring import (
    compute_indicator_score,
    heuristic_risk_score,
    percentile_rank,
    percentile_risk_score,
    z_score,
)
from pipeline.schemas import (
    CommoditiesEnvelope,
    CryptoEnvelope,
    EquitiesEnvelope,
    MacroDataset,
    MacroEnvelope,
    RiskDimension,
    RiskIndicator,
    RiskModelResult,
)


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


def test_regime_does_not_treat_unmeasured_inputs_as_passing() -> None:
    regime, evidence = regime_mod.infer_regime({"yield_curve_10y2y": 0.8})
    assert regime == "indeterminate"
    assert evidence == []


def _macro_with_rates(*, value: float | None = None) -> MacroDataset:
    """A MacroDataset built entirely from the factory (#73: no direct constructor calls).

    Defaults to the four rate indicators plus VIX in the canonical volatility group; passing
    ``value`` swaps the VIX indicator in (used by the level-threshold test).
    """
    from pipeline.schemas import MacroEnvelope
    from tests.pipeline.factories import make_envelope, make_macro_indicator, make_macro_payload

    if value is not None:
        volatility = [make_macro_indicator(key="vixcls", label="VIX", value=value, unit="index", source="FRED")]
        payload = make_macro_payload(rates=[], credit=[], volatility=volatility, inflation=[], labor=[], liquidity=[], fx=[])
    else:
        payload = make_macro_payload(
            rates=[
                make_macro_indicator(key="dgs10", label="10Y", value=4.2, source="FRED"),
                make_macro_indicator(key="dgs2", label="2Y", value=3.8, source="FRED"),
                make_macro_indicator(key="dfii10", label="Real", value=1.9, source="FRED"),
            ],
            credit=[make_macro_indicator(key="bamlh0a0hym2", label="HY", value=4.5, source="FRED")],
            volatility=[make_macro_indicator(key="vixcls", label="VIX", value=25.0, unit="index", source="FRED")],
            fx=[],
        )
    return MacroEnvelope.model_validate(make_envelope("macro", payload=payload)).payload


def _synthetic_context() -> dict:
    return {
        "macro": _macro_with_rates(),
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
    assert result.calibration_policy_version == "1.0.0"
    assert result.calibration_status == "provisional"
    assert "definitive probability" not in result.disclaimer or "modeled estimate" in result.disclaimer


def test_golden_score_preserves_current_outputs() -> None:
    result = RiskModel().score(_synthetic_context())
    assert result.total_score == 54.7
    assert result.risk_level == "caution"
    assert [driver.indicator_key for driver in result.top_drivers] == [
        "hy_oas", "cross_asset_confirmation", "real_rate_dfii10", "vix", "yield_curve_10y2y"
    ]


def test_risk_evidence_state_and_bounds_are_published() -> None:
    result = RiskModel().score(_synthetic_context())

    assert result.evidence_state == "partial"
    assert result.evidence_coverage == pytest.approx(result.confidence_factors["coverage"])
    assert result.score_lower_bound <= result.total_score <= result.score_upper_bound
    macro = next(d for d in result.dimensions if d.key == "macro")
    assert macro.evidence_state == "partial"
    assert macro.missing_indicators == ["dollar_index"]


def test_missing_evidence_is_insufficient_with_full_deterministic_bounds() -> None:
    result = RiskModel().score({})

    assert result.evidence_state == "insufficient_evidence"
    assert result.evidence_coverage == 0.0
    assert result.score_lower_bound == 0.0
    assert result.score_upper_bound == 100.0
    assert all(d.evidence_state == "insufficient_evidence" for d in result.dimensions)


def test_complete_evidence_collapses_bounds_to_point_estimate(monkeypatch) -> None:
    from tests.pipeline.factories import make_envelope, make_macro_indicator, make_macro_payload

    # Treat the proxy inputs as fully trusted for this semantic test; their proxy disclosure
    # remains present, but the evidence-state calculation must support a complete run.
    monkeypatch.setattr(conf_mod, "proxy_discount_factor", lambda *args, **kwargs: 1.0)
    payload = make_macro_payload(
        rates=[
            make_macro_indicator(key="dgs10", label="10Y", value=4.2, source="FRED"),
            make_macro_indicator(key="dgs2", label="2Y", value=3.8, source="FRED"),
            make_macro_indicator(key="dfii10", label="Real", value=1.9, source="FRED"),
        ],
        credit=[
            make_macro_indicator(key="bamlh0a0hym2", label="HY", value=4.5, source="FRED"),
            make_macro_indicator(key="bamlc0a0cm", label="IG", value=1.2, source="FRED"),
        ],
        volatility=[make_macro_indicator(key="vixcls", label="VIX", value=25.0, unit="index", source="FRED")],
        liquidity=[
            make_macro_indicator(key="walcl", label="Assets", value=6600000, source="FRED"),
            make_macro_indicator(key="rrpontsyd", label="RRP", value=100.0, source="FRED"),
        ],
        fx=[make_macro_indicator(key="dtwexbgs", label="Dollar", value=98.0, source="FRED")],
    )
    ctx = _synthetic_context()
    ctx["macro"] = MacroEnvelope.model_validate(make_envelope("macro", payload=payload)).payload

    result = RiskModel().score(ctx)

    assert result.evidence_state == "complete"
    assert all(d.evidence_state == "complete" for d in result.dimensions)
    assert result.score_lower_bound == result.score_upper_bound == result.total_score


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


def test_vix_uses_canonical_volatility_group_for_risk_and_regime(monkeypatch) -> None:
    captured: dict = {}

    def capture_regime(ctx: dict) -> tuple[str, list[str]]:
        captured.update(ctx)
        return "indeterminate", []

    monkeypatch.setattr(regime_mod, "infer_regime", capture_regime)
    result = RiskModel().score(_synthetic_context())
    vix = next(
        ind for dim in result.dimensions if dim.key == "volatility"
        for ind in dim.indicators if ind.key == "vix"
    )

    assert vix.value == 25.0
    assert captured["vix"] == 25.0


def test_vix_in_rates_is_not_used_as_a_compatibility_fallback() -> None:
    from pipeline.schemas import MacroEnvelope
    from tests.pipeline.factories import make_envelope, make_macro_indicator, make_macro_payload

    payload = make_macro_payload(
        rates=[make_macro_indicator(key="vixcls", label="VIX", value=45.0, unit="index", source="FRED")],
        credit=[], volatility=[], inflation=[], labor=[], liquidity=[], fx=[]
    )
    ctx = {"macro": MacroEnvelope.model_validate(make_envelope("macro", payload=payload)).payload}
    result = RiskModel().score(ctx)
    vix = next(
        ind for dim in result.dimensions if dim.key == "volatility"
        for ind in dim.indicators if ind.key == "vix"
    )

    assert vix.value is None
    realized = next(
        ind for dim in result.dimensions if dim.key == "volatility"
        for ind in dim.indicators if ind.key == "realized_vol"
    )
    volatility = next(dim for dim in result.dimensions if dim.key == "volatility")
    assert realized.value is None
    assert volatility.coverage == 0.0
    assert result.regime == "indeterminate"


def test_build_risk_context_carries_canonical_vix_and_realized_volatility() -> None:
    from pipeline.run import _build_risk_context
    from tests.pipeline.factories import make_envelope

    histories = {
        "SPY": [
            {"date": f"2026-01-{(i % 28) + 1:02d}", "close": 100.0 + i * 0.2 + (i % 5) * 0.1}
            for i in range(260)
        ]
    }
    context = _build_risk_context(
        macro=MacroEnvelope.model_validate(make_envelope("macro", payload={
            "rates": [
                {"key": "dgs10", "label": "10Y", "value": 4.2, "source": "FRED"},
                {"key": "dgs2", "label": "2Y", "value": 3.8, "source": "FRED"},
                {"key": "dfii10", "label": "Real", "value": 1.9, "source": "FRED"},
            ],
            "credit": [],
            "volatility": [{"key": "vixcls", "label": "VIX", "value": 25.0, "unit": "index", "source": "FRED"}],
            "inflation": [], "labor": [], "liquidity": [], "fx": [],
            "fedwatch": None,
        })),
        equities=EquitiesEnvelope.model_validate(make_envelope("equities")),
        crypto=CryptoEnvelope.model_validate(make_envelope("crypto")),
        commodities=CommoditiesEnvelope.model_validate(make_envelope("commodities")),
        histories=histories,
        qualities=[1.0],
        prev_total_score=None,
        prev_dim_scores=None,
        risk_history=[],
        series_history={},
    )

    assert context["cross_asset"]["vix"] == 25.0
    assert context["trend"]["realized_vol"] is not None

    result = RiskModel().score(context)
    volatility = next(d for d in result.dimensions if d.key == "volatility")
    assert next(i for i in volatility.indicators if i.key == "vix").value == 25.0
    assert next(i for i in volatility.indicators if i.key == "realized_vol").value is not None


def test_cross_asset_signals_are_null_aware_and_new_proxies_are_diagnostic_only() -> None:
    from pipeline.run import _build_risk_context

    histories = {
        "SPY": [{"close": 100.0}, {"close": 99.0}],
        "IWM": [{"close": 100.0}, {"close": 98.0}],
        "XLY": [{"close": 100.0}, {"close": 99.0}],
        "XLP": [{"close": 100.0}, {"close": 100.5}],
        "HYG": [{"close": 100.0}, {"close": 99.5}],
        "IEF": [{"close": 100.0}, {"close": 100.2}],
    }
    empty = SimpleNamespace(payload=SimpleNamespace(assets=[]))
    context = _build_risk_context(
        macro=SimpleNamespace(payload=_macro_with_rates()),
        equities=empty,
        crypto=empty,
        commodities=empty,
        histories=histories,
        qualities=[1.0],
        prev_total_score=None,
        prev_dim_scores=None,
        risk_history=[],
        series_history={},
        market_provenance={"provider": "yfinance", "used_fallback": True},
    )

    rows = {row["key"]: row for row in context["cross_asset"]["signals"]}
    assert len(rows) == 10
    assert rows["cyclicals_defensives_relative"]["triggered"] is True
    assert rows["hy_treasury_relative"]["triggered"] is True
    assert rows["cyclicals_defensives_relative"]["status"] == "degraded"
    assert rows["cyclicals_defensives_relative"]["production_scoring"] is False
    assert context["cross_asset"]["observed_signal_count"] == 5
    # New diagnostic signals must not silently change the gated production aggregate.
    assert context["cross_asset"]["production_scoring_signal_count"] == 8

    result = RiskModel().score(context)
    assert {signal.key for signal in result.cross_asset_signals} == set(rows)
    new_signal = next(signal for signal in result.cross_asset_signals if signal.key == "hy_treasury_relative")
    assert new_signal.is_proxy is True
    assert new_signal.production_scoring is False


def test_cross_asset_missing_inputs_do_not_count_as_benign() -> None:
    from pipeline.run import _build_risk_context

    empty = SimpleNamespace(payload=SimpleNamespace(assets=[]))
    context = _build_risk_context(
        macro=SimpleNamespace(payload=MacroDataset(rates=[], credit=[], volatility=[], inflation=[], labor=[], liquidity=[], fx=[], fedwatch=None)),
        equities=empty,
        crypto=empty,
        commodities=empty,
        histories={},
        qualities=[1.0],
        prev_total_score=None,
        prev_dim_scores=None,
        risk_history=[],
        series_history={},
    )

    assert context["cross_asset"]["confirmation"] is None
    result = RiskModel().score(context)
    cross_asset = next(dimension for dimension in result.dimensions if dimension.key == "cross_asset")
    assert next(indicator for indicator in cross_asset.indicators if indicator.key == "cross_asset_confirmation").value is None
    assert cross_asset.coverage == 0.0


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
    low_ctx["macro"] = _macro_with_rates(value=12.0)
    low = model.score(low_ctx)
    high_ctx = _synthetic_context()
    high_ctx["macro"] = _macro_with_rates(value=45.0)
    high = model.score(high_ctx)
    assert high.total_score > low.total_score


def test_confidence_consistency() -> None:
    assert conf_mod.compute_confidence(1.0, 1.0, 1.0) == 1.0
    assert conf_mod.compute_confidence(0.5, 0.5, 0.5) == 0.5
    assert conf_mod.consistency_from_dimension_scores([20, 20, 20]) == 1.0
    assert conf_mod.consistency_from_dimension_scores([0, 100]) < 0.5


def test_thresholds_are_sorted_and_reject_unknown_rules() -> None:
    thresholds = _parse_thresholds({"crisis": {"gte": 90}, "risk_on": {"lt": 20}})
    assert thresholds[0][0] == "risk_on"
    assert thresholds[1][0] == "crisis"
    with pytest.raises(ValueError, match="unknown risk level"):
        _parse_thresholds({"unknown": {"gte": 0}})



# ---------- #67: config == code, direction agrees with the scoring table ----------

def _risk_result() -> RiskModelResult:
    """Score the standard synthetic context once (shared by the #67 assertions)."""
    return RiskModel().score(_synthetic_context())


def _indicator_by_key(result: RiskModelResult, key: str):
    for dim in result.dimensions:
        for ind in dim.indicators:
            if ind.key == key:
                return dim.key, ind
    return None, None


def test_inverted_curve_scores_high_risk() -> None:
    """A negative 10Y-2Y spread (inverted curve) must score as HIGH risk.

    HEURISTIC_RULES["yield_curve_10y2y"] maps -0.5 -> 95; the declaration used to say
    `higher_is_riskier`, which contradicted the table (#67 group 5).
    """
    from pipeline.schemas import MacroIndicator
    from tests.pipeline.factories import make_macro_indicator

    ctx = _synthetic_context()
    # dgs10 = 3.0, dgs2 = 4.0 -> curve = -1.0 (inverted), no history -> heuristic path
    macro = _macro_with_rates().model_copy(
        update={"rates": [
            MacroIndicator.model_validate(make_macro_indicator(key="dgs10", label="10Y", value=3.0, source="FRED")),
            MacroIndicator.model_validate(make_macro_indicator(key="dgs2", label="2Y", value=4.0, source="FRED")),
        ]}
    )
    ctx["macro"] = macro
    result = RiskModel().score(ctx)
    dim_key, ind = _indicator_by_key(result, "yield_curve_10y2y")
    assert dim_key == "macro"
    assert ind is not None
    assert ind.risk_score >= 90, f"inverted curve must score high, got {ind.risk_score}"
    assert ind.direction == "lower_is_riskier", (
        "yield_curve_10y2y declares lower_is_riskier (inversion is high risk), got "
        f"{ind.direction}"
    )


def test_hy_oas_counted_once_in_a_scored_result() -> None:
    """hy_oas appears in exactly one dimension of a scored result, at weight 10.0."""
    result = _risk_result()
    sites = [
        (dim.key, ind.weight)
        for dim in result.dimensions
        for ind in dim.indicators
        if ind.key == "hy_oas"
    ]
    assert sites == [("liquidity_credit", 10.0)], f"hy_oas must be scored once at 10.0, found {sites}"


def test_ig_oas_is_scored_under_liquidity_credit() -> None:
    """ig_oas moved from macro to liquidity_credit, preserving weight 5.0 (#67 group 4)."""
    result = _risk_result()
    dim_key, ind = _indicator_by_key(result, "ig_oas")
    assert dim_key == "liquidity_credit", f"ig_oas must live under liquidity_credit, found {dim_key}"
    assert ind is not None and ind.weight == 5.0
    assert "bamlc0a0cm" not in {i.key for i in result.dimensions[0].indicators}  # macro has no credit keys
    # No indicator key is registered in two dimensions in the scored output (ruling B).
    seen: dict[str, str] = {}
    for dim in result.dimensions:
        for ind in dim.indicators:
            assert ind.key not in seen, f"{ind.key} registered in {seen[ind.key]} and {dim.key}"
            seen[ind.key] = dim.key


def test_macro_dimension_has_exactly_four_indicators() -> None:
    """After the hy_oas/ig_oas removals, macro is rates + curve + dollar + nominal yield."""
    result = _risk_result()
    macro = next(d for d in result.dimensions if d.key == "macro")
    assert {i.key for i in macro.indicators} == {
        "real_rate_dfii10", "yield_curve_10y2y", "dollar_index", "dgs10",
    }



# ---------- #68: top drivers reflect each indicator's own weight ----------

def _liquidity_only_context() -> dict:
    """A synthetic context where the ONLY available indicators live in liquidity_credit:
    hy_oas (weight 10.0) and fed_balance_sheet (weight 5.0), both scoring exactly 50
    (hy_oas heuristic maps 3.8 -> 50; fed_balance_sheet has no heuristic and falls back).
    The old computation credited both with the dimension's whole weight, making them
    indistinguishable in the driver list.
    """
    from pipeline.schemas import MacroEnvelope
    from tests.pipeline.factories import make_envelope, make_macro_indicator, make_macro_payload

    payload = make_macro_payload(
        rates=[],
        credit=[make_macro_indicator(key="bamlh0a0hym2", label="HY", value=3.8, source="FRED")],
        liquidity=[make_macro_indicator(key="walcl", label="Fed Balance Sheet", value=8.2e6, source="FRED")],
        fx=[],
    )
    ctx = _synthetic_context()
    ctx["macro"] = MacroEnvelope.model_validate(make_envelope("macro", payload=payload)).payload
    return ctx


def _expected_contributions(result: RiskModelResult) -> dict[str, float]:
    """The #68 spec: indicator i's contribution is its own share of weight within its
    dimension, times the dimension's share of total weight, times the risk score:
    (d.effective_weight / W) * (i.weight / V_d) * i.risk_score."""
    out: dict[str, float] = {}
    denom = sum(d.effective_weight for d in result.dimensions) or 1.0
    for d in result.dimensions:
        available = [i for i in d.indicators if i.value is not None]
        v = sum(i.weight for i in available) or 1.0
        for ind in available:
            out[ind.key] = round(d.effective_weight / denom * (ind.weight / v) * ind.risk_score, 4)
    return out


def test_driver_contribution_uses_indicator_weight() -> None:
    """#68: an indicator's contribution scales with its OWN weight, not the dimension's."""
    result = RiskModel().score(_liquidity_only_context())
    drivers = {d.indicator_key: d.contribution for d in result.top_drivers}

    hy = next(d for d in result.dimensions if d.key == "liquidity_credit")
    scores = {i.key: i.risk_score for i in hy.indicators if i.value is not None}
    assert scores["hy_oas"] == scores["fed_balance_sheet"] == 50.0

    expected = _expected_contributions(result)
    # Both liquidity indicators land in the published top-5 (they are the only drivers).
    assert drivers["hy_oas"] == pytest.approx(expected["hy_oas"], rel=1e-3)
    assert drivers["fed_balance_sheet"] == pytest.approx(expected["fed_balance_sheet"], rel=1e-3)
    # hy_oas (10.0) outranks fed_balance_sheet (5.0) by exactly the weight ratio.
    assert drivers["hy_oas"] > drivers["fed_balance_sheet"]
    assert abs(drivers["hy_oas"] / drivers["fed_balance_sheet"] - 2.0) < 1e-3


def test_same_dimension_different_weights_differ() -> None:
    """The specific defect: same dimension, same score, different weight -> different
    contribution. hy_oas (10.0) and fed_balance_sheet (5.0) are no longer identical."""
    result = RiskModel().score(_liquidity_only_context())
    drivers = {d.indicator_key: d.contribution for d in result.top_drivers}
    assert drivers["hy_oas"] != drivers["fed_balance_sheet"]
    assert drivers["hy_oas"] == pytest.approx(2.0 * drivers["fed_balance_sheet"], rel=1e-3)


def test_contributions_reconcile_with_composite() -> None:
    """The sum of all indicator contributions reconciles with the composite score.

    Tolerance: 0.01 — the composite is rounded to 2 decimals and each contribution to 4,
    so the sum cannot drift by more than dimension-score rounding (each ≤ 0.005) plus
    total-score rounding (≤ 0.005).
    """
    result = RiskModel().score(_synthetic_context())
    expected = _expected_contributions(result)
    assert abs(sum(expected.values()) - result.total_score) <= 0.01, (
        f"indicator contributions must reconcile with the composite: "
        f"sum={sum(expected.values()):.4f} total_score={result.total_score}"
    )
    # The model's published top-5 must match the spec formula (not a different one).
    for d in result.top_drivers:
        assert d.contribution == pytest.approx(expected[d.indicator_key], rel=1e-3), (
            f"published contribution for {d.indicator_key} does not match the indicator-share formula"
        )


def test_driver_ordering_is_pinned() -> None:
    """Regression pin: the top-driver ordering over `_synthetic_context()`.

    Changes to the contribution computation must show up here deliberately, not silently.
    """
    result = RiskModel().score(_synthetic_context())
    keys = [d.indicator_key for d in result.top_drivers]
    # The pinned ordering after #68 (indicator-share contributions, sorted descending).
    assert keys == ["hy_oas", "cross_asset_confirmation", "real_rate_dfii10", "vix", "yield_curve_10y2y"], (
        f"top-driver ordering drifted: {keys}"
    )
    assert all(
        result.top_drivers[i].contribution >= result.top_drivers[i + 1].contribution
        for i in range(len(result.top_drivers) - 1)
    )


# ---------- #69: proxy-backed indicators stop inflating coverage and confidence ----------

def _synthetic_ctx_confidence() -> float:
    """The overall confidence for `_synthetic_context()` (equity_structure is 5/5 proxies)."""
    return RiskModel().score(_synthetic_context()).confidence


def test_proxy_indicator_discounts_coverage() -> None:
    """Availability and proxy trust are published separately (#194)."""
    result = RiskModel().score(_synthetic_context())
    es = next(d for d in result.dimensions if d.key == "equity_structure")
    assert all(i.is_proxy for i in es.indicators if i.value is not None)
    assert es.coverage == 1.0
    assert es.effective_coverage == pytest.approx(0.8, abs=1e-4)


def test_coverage_uses_configured_indicator_weights() -> None:
    model = RiskModel()
    high_weight_missing = RiskIndicator(
        key="high_weight", label="High weight", risk_score=50, weight=10, source="test", is_proxy=False
    )
    low_weight_available = RiskIndicator(
        key="low_weight", label="Low weight", value=1, risk_score=50, weight=1, source="test", is_proxy=False
    )
    dimensions, _, _ = model._build_dimensions(
        {}, {"macro": lambda _: [high_weight_missing, low_weight_available]}, {}, 0.8
    )

    assert dimensions[0].coverage == pytest.approx(1 / 11, abs=1e-4)
    assert dimensions[0].effective_coverage == pytest.approx(1 / 11, abs=1e-4)


def test_legacy_risk_dimension_leaves_trust_coverage_unset() -> None:
    dimension = RiskDimension.model_validate(
        {
            "key": "macro",
            "label": "Macro",
            "weight": 20,
            "effective_weight": 20,
            "score": 50,
            "coverage": 0.75,
        }
    )

    assert dimension.effective_coverage is None


def test_proxy_dimension_confidence_baseline_reduced() -> None:
    """#69: equity_structure/cross_asset show a permanently reduced confidence baseline."""
    result = RiskModel().score(_synthetic_context())
    es = next(d for d in result.dimensions if d.key == "equity_structure")
    ca = next(d for d in result.dimensions if d.key == "cross_asset")
    assert es.coverage == 1.0 and ca.coverage == 1.0
    assert es.effective_coverage < 1.0 and ca.effective_coverage < 1.0
    # A fully-covered run would score higher; the baseline is honest, not a regression.
    assert result.confidence < 1.0
    assert "coverage" in result.confidence_factors


def test_proxy_and_degrade_compound() -> None:
    """#69 ruling F: proxy AND degraded-provider discounts compound to 0.64, not 0.8."""
    from pipeline.degrade import degrade_factor
    from pipeline.risk.confidence import DEFAULT_PROXY_DISCOUNT_FACTOR

    ctx = _synthetic_context()
    ctx["data_quality"] = 0.8  # a degraded run (degrade factor applied upstream)
    result = RiskModel().score(ctx)
    # A proxy driver in the same run compounds both discounts.
    proxy_driver = next(d for d in result.top_drivers if d.is_proxy)
    assert proxy_driver.discount == pytest.approx(
        DEFAULT_PROXY_DISCOUNT_FACTOR * degrade_factor(), rel=1e-4
    ), "proxy + degraded provider must compound to factor × proxy_discount (0.64)"


def test_discount_uses_shared_constant(monkeypatch) -> None:
    """#69: the proxy discount is its own knob — patching the config key moves it, and
    patching the degrade factor does NOT."""
    import pipeline.risk.confidence as conf_mod

    # The accessor reads its own config key (range-checked), independent of the degrade factor.
    assert conf_mod.proxy_discount_factor(risk_model={"confidence": {"proxy_discount_factor": 0.5}}) == 0.5
    with pytest.raises(ValueError):
        conf_mod.proxy_discount_factor(risk_model={"confidence": {"proxy_discount_factor": 0.0}})
    with pytest.raises(ValueError):
        conf_mod.proxy_discount_factor(risk_model={"confidence": {"proxy_discount_factor": 1.5}})

    # The model's coverage discount follows the knob.
    monkeypatch.setattr(conf_mod, "proxy_discount_factor", lambda *a, **k: 0.5)
    result = RiskModel().score(_synthetic_context())
    es = next(d for d in result.dimensions if d.key == "equity_structure")
    assert es.coverage == 1.0
    assert es.effective_coverage == pytest.approx(0.5, abs=1e-4)


# ---------- #71: the regime says indeterminate when nothing fired ----------

def test_empty_context_yields_indeterminate() -> None:
    """#71: with no condition firing, the regime is indeterminate, not a benign fallback."""
    regime, evidence = regime_mod.infer_regime({})
    assert regime == "indeterminate", (
        f"all-absent input must not guess a benign regime, got {regime!r}"
    )
    assert evidence == []


def test_evidence_contains_only_fired_conditions() -> None:
    """#71: nothing is appended unconditionally to the evidence list."""
    _, evidence = regime_mod.infer_regime({})
    assert evidence == []
    assert all("default:" not in line for line in evidence)


def test_indeterminate_confidence_is_not_full() -> None:
    """#71: an all-absent run is indeterminate and its confidence reflects the absence
    of evidence — not full confidence."""
    result = RiskModel().score({})
    assert result.regime == "indeterminate"
    assert result.confidence < 1.0


def test_dollar_index_absent_from_regime_context(monkeypatch) -> None:
    """#71: no dxy/dollar_index key reaches infer_regime (the dead path is gone)."""
    captured: dict = {}

    def capture(ctx: dict) -> tuple[str, list[str]]:
        captured["ctx"] = ctx
        return "goldilocks", ["captured"]

    monkeypatch.setattr(regime_mod, "infer_regime", capture)
    RiskModel().score(_synthetic_context())
    assert "dxy" not in captured["ctx"]
    assert "dollar_index" not in captured["ctx"]


def test_dollar_index_removal_changes_no_regime() -> None:
    """#71: dxy was never read by any condition — a dollar value changes NO regime outcome.

    This is the regression pin for the dead-code claim: the same context with and without
    a dollar value yields the identical regime and evidence.
    """
    from pipeline.schemas import MacroEnvelope
    from tests.pipeline.factories import make_envelope, make_macro_indicator, make_macro_payload

    # Identical to _synthetic_context()'s macro EXCEPT for the fx group (dollar present).
    with_dollar = dict(_synthetic_context())
    payload = make_macro_payload(
        rates=[
            make_macro_indicator(key="dgs10", label="10Y", value=4.2, source="FRED"),
            make_macro_indicator(key="dgs2", label="2Y", value=3.8, source="FRED"),
            make_macro_indicator(key="dfii10", label="Real", value=1.9, source="FRED"),
        ],
        credit=[make_macro_indicator(key="bamlh0a0hym2", label="HY", value=4.5, source="FRED")],
        volatility=[make_macro_indicator(key="vixcls", label="VIX", value=25.0, unit="index", source="FRED")],
        fx=[make_macro_indicator(key="dtwexbgs", label="Dollar", value=98.0, source="FRED")],
    )
    with_dollar["macro"] = MacroEnvelope.model_validate(make_envelope("macro", payload=payload)).payload
    without = _synthetic_context()  # fx=[] — everything else identical

    r_with = RiskModel().score(with_dollar)
    r_without = RiskModel().score(without)
    assert r_with.regime == r_without.regime
    assert r_with.regime_evidence == r_without.regime_evidence
