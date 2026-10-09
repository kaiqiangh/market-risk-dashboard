"""Derived value-history tests (#D3).

Three properties matter and each is asserted here rather than assumed:

1. **Definition parity.** A derived series must be the same statistic as the live indicator it
   backs, evaluated at an earlier date. If it drifts, a percentile window over it is
   meaningless — the defect this module exists to fix would simply move one level down.
2. **Point-in-time.** No derived value may depend on a close dated after it.
3. **The gate is inert when off.** The shipped config must score exactly as before, including
   when a context happens to carry derived series.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from pipeline.indicators.breadth import breadth_snapshot
from pipeline.indicators.derived_series import (
    CROSS_ASSET_SIGNAL_INPUTS,
    DEFAULT_BENCHMARK,
    MIN_SERIES_SAMPLES,
    SERIES_SPECS,
    cross_asset_series_requirement,
    derive_report,
    derive_series,
    series_feasibility,
)
from pipeline.indicators.technical import realized_vol
from pipeline.indicators.trend import trend_snapshot
from pipeline.risk.model import DERIVED_HISTORY_KEYS, RiskModel
from pipeline.settings import PROJECT_ROOT, Settings

#: Enough benchmark sessions that every spec clears its lookback plus MIN_SERIES_SAMPLES
#: (the longest lookback is 200, so >= 260).
_SESSIONS = 320

#: Per-symbol phase offsets, so the relative-strength series is not identically zero.
_PHASES = {"SPY": 0.0, "IWM": 1.3, "SOXX": 2.7}

_SPECS_BY_KEY = {spec.key: spec for spec in SERIES_SPECS}


def _history(symbol: str, sessions: int = _SESSIONS) -> list[dict[str, Any]]:
    """A deterministic, quietly oscillating close series with a symbol-specific phase."""
    start = date(2019, 1, 1)
    phase = _PHASES.get(symbol, 0.0)
    return [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "close": round(100.0 + 12.0 * math.sin(index / 11.0 + phase) + 0.07 * index, 4),
        }
        for index in range(sessions)
    ]


def _last_date(sessions: int = _SESSIONS) -> str:
    return _history("SPY", sessions=sessions)[-1]["date"]


@pytest.fixture(scope="module")
def histories() -> dict[str, list[dict[str, Any]]]:
    return {symbol: _history(symbol) for symbol in ("SPY", "IWM", "SOXX")}


@pytest.fixture(scope="module")
def report(histories: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return derive_report(histories)


# ---- feasibility and disclosure ------------------------------------------------------------


def test_series_feasibility_is_the_calendar_after_the_lookback() -> None:
    histories = {"SPY": _history("SPY", sessions=100)}

    assert series_feasibility(histories, _SPECS_BY_KEY["momentum_3m"]) == 100 - 64
    assert series_feasibility(histories, _SPECS_BY_KEY["drawdown_52w"]) == 100 - 1
    # No benchmark at all: the feasibility is zero, not an exception and not a negative.
    assert series_feasibility({}, _SPECS_BY_KEY["momentum_3m"]) == 0
    assert series_feasibility({"AAPL": _history("AAPL")}, _SPECS_BY_KEY["momentum_3m"]) == 0


def test_every_key_is_withheld_with_a_reason_when_nothing_was_collected() -> None:
    report = derive_report({})

    assert report["series"] == {}
    assert report["derived_keys"] == []
    assert report["benchmark_observations"] == 0
    assert set(report["withheld"]) == DERIVED_HISTORY_KEYS
    assert report["withheld"]["momentum_3m"]["reason"] == "no_source"
    assert report["withheld"]["cross_asset_confirmation"]["reason"] == "partial_signal_coverage"


def test_an_absent_relative_target_is_reported_as_no_source_not_short_history(
    histories: dict[str, list[dict[str, Any]]],
) -> None:
    """The reason must name the actual cause: a missing symbol, not a short window."""
    report = derive_report({"SPY": histories["SPY"]})

    assert report["withheld"]["small_cap_relative"]["reason"] == "no_source"
    assert "IWM" in report["withheld"]["small_cap_relative"]["detail"]
    assert report["withheld"]["semis_relative"]["reason"] == "no_source"
    assert "SOXX" in report["withheld"]["semis_relative"]["detail"]
    # The benchmark-only specs are unaffected by the missing relative targets.
    assert {"realized_vol", "drawdown_52w", "momentum_3m"} <= set(report["derived_keys"])


def test_keys_shorter_than_the_percentile_minimum_are_withheld_with_their_counts() -> None:
    report = derive_report({"SPY": _history("SPY", sessions=80)})
    withheld = report["withheld"]["momentum_3m"]

    assert withheld["reason"] == "insufficient_history"
    assert withheld["observations"] == 16  # 80 sessions - 64 lookback
    assert withheld["required_observations"] == MIN_SERIES_SAMPLES
    assert withheld["lookback_sessions"] == 64
    # drawdown_52w still clears the minimum on the same calendar.
    assert "drawdown_52w" in report["derived_keys"]


def test_cross_asset_requirement_separates_derivable_from_whether_a_series_exists() -> None:
    market = {name: [{"close": 1.0}] for source, name in CROSS_ASSET_SIGNAL_INPUTS.values() if source == "market"}
    macro = {name: [{"value": 1.0}] for source, name in CROSS_ASSET_SIGNAL_INPUTS.values() if source == "macro_series"}
    complete = cross_asset_series_requirement(market, macro)
    partial = cross_asset_series_requirement({"SPY": [{"close": 1.0}]}, {})

    # Every input is present, and there is still no series: the two facts are reported apart.
    assert complete["derivable"] is True
    assert complete["reason"] == "not_implemented"
    assert complete["missing_inputs"] == []
    assert partial["derivable"] is False
    assert partial["reason"] == "partial_signal_coverage"
    assert partial["observed_signals"] == 1
    assert partial["required_signals"] == len(CROSS_ASSET_SIGNAL_INPUTS)
    assert "small_cap_underperformance:IWM" in partial["missing_inputs"]


# ---- definition parity ---------------------------------------------------------------------


def test_each_derived_series_ends_at_the_live_indicator_value_it_backs(
    report: dict[str, Any], histories: dict[str, list[dict[str, Any]]]
) -> None:
    """The crux: a series and its live value are the same statistic at different dates."""
    live_trend = trend_snapshot(histories)
    live_breadth = breadth_snapshot(histories)

    for key in ("realized_vol", "price_vs_ma200", "drawdown_52w", "momentum_3m"):
        assert report["series"][key][-1] == pytest.approx(live_trend[key]), key
    for key in (
        "small_cap_relative",
        "semis_relative",
        "new_highs_ratio",
        "new_lows_ratio",
        "breadth_above_ma200",
    ):
        assert report["series"][key][-1] == pytest.approx(live_breadth[key]), key


def test_every_feasible_key_is_derived_on_a_full_length_calendar(report: dict[str, Any]) -> None:
    assert set(report["derived_keys"]) == DERIVED_HISTORY_KEYS - {"cross_asset_confirmation"}
    assert set(report["observed"]) == set(report["derived_keys"])
    assert report["benchmark"] == DEFAULT_BENCHMARK
    assert report["benchmark_observations"] == _SESSIONS
    assert report["universe_symbols"] == 3
    for key, detail in report["observed"].items():
        assert detail["observations"] >= MIN_SERIES_SAMPLES, key
        assert detail["last_date"] == _last_date()


def test_derive_series_is_the_report_series(histories: dict[str, list[dict[str, Any]]]) -> None:
    assert derive_series(histories) == derive_report(histories)["series"]


def test_the_realized_vol_series_uses_the_trend_snapshot_window() -> None:
    """A direct check of the 20-session window, independent of the report's shape."""
    rows = _history("SPY")

    assert derive_series({"SPY": rows})["realized_vol"][-1] == realized_vol(
        [row["close"] for row in rows], 20
    )


# ---- point-in-time -------------------------------------------------------------------------


def test_a_derived_series_never_reads_a_close_after_its_date(
    histories: dict[str, list[dict[str, Any]]], report: dict[str, Any]
) -> None:
    """Truncating the input must truncate the outputs, never change an earlier value."""
    head = derive_report({symbol: rows[:200] for symbol, rows in histories.items()})["series"]

    assert head, "the truncated calendar must still derive something to compare"
    for key, values in head.items():
        assert report["series"][key][: len(values)] == values, key


# ---- the model gate ------------------------------------------------------------------------


def _shipped_config_text() -> str:
    return (PROJECT_ROOT / "config" / "risk_model.yaml").read_text(encoding="utf-8")


def _settings_with_gate(tmp_path: Any, enabled: bool) -> Settings:
    """The shipped config with ``scoring.derived_history.enabled`` rewritten in a temp dir."""
    raw = yaml.safe_load(_shipped_config_text())
    raw["scoring"]["derived_history"] = {"enabled": enabled}
    (tmp_path / "risk_model.yaml").write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return Settings(_env_file=None, config_dir=tmp_path)


def _context_with_derived_series(series: dict[str, list[float]]) -> dict[str, Any]:
    """A minimal context whose computed indicators all carry a live value."""
    return {
        "macro": SimpleNamespace(rates=[], fx=[], liquidity=[], volatility=[], credit=[]),
        "breadth": {
            "breadth_above_ma200": 0.55,
            "new_highs_ratio": 0.4,
            "new_lows_ratio": 0.2,
            "small_cap_relative": -1.0,
            "semis_relative": 2.0,
        },
        "trend": {
            "price_vs_ma200": 8.0,
            "drawdown_52w": -5.0,
            "momentum_3m": 3.0,
            "realized_vol": 18.0,
        },
        "cross_asset": {"confirmation": 0.6},
        "data_quality": 0.9,
        "derived_indicator_series": series,
    }


def _indicator(result: Any, key: str) -> Any:
    return next(
        indicator
        for dimension in result.dimensions
        for indicator in dimension.indicators
        if indicator.key == key
    )


def test_the_shipped_config_ships_the_gate_off() -> None:
    assert RiskModel(Settings(_env_file=None)).derived_history_enabled is False


def test_a_non_mapping_derived_history_block_is_rejected(tmp_path: Any) -> None:
    raw = yaml.safe_load(_shipped_config_text())
    raw["scoring"]["derived_history"] = "yes please"
    (tmp_path / "risk_model.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="derived_history must be a mapping"):
        RiskModel(Settings(_env_file=None, config_dir=tmp_path))


def test_the_gate_off_ignores_published_derived_series(report: dict[str, Any]) -> None:
    """A caller cannot move a published score by publishing series the model did not ask for."""
    model = RiskModel(Settings(_env_file=None))
    realized = _indicator(model.score(_context_with_derived_series(report["series"])), "realized_vol")

    assert model.derived_history_enabled is False
    assert realized.percentile is None  # the heuristic table still scores it
    assert realized.z_score is None
    assert realized.risk_score == 42.0  # heuristic realized_vol 18.0


def test_the_gate_on_puts_a_derived_series_on_the_percentile_path(
    tmp_path: Any, report: dict[str, Any]
) -> None:
    model = RiskModel(_settings_with_gate(tmp_path, True))
    result = model.score(_context_with_derived_series(report["series"]))

    assert model.derived_history_enabled is True
    for key in ("realized_vol", "drawdown_52w", "momentum_3m", "price_vs_ma200"):
        indicator = _indicator(result, key)
        assert indicator.percentile is not None, key
        assert indicator.z_score is not None, key


def test_a_derived_series_below_the_percentile_minimum_falls_back_to_the_table(
    tmp_path: Any,
) -> None:
    """A short series must not be scored — it decays to the heuristic table, not to zeros."""
    model = RiskModel(_settings_with_gate(tmp_path, True))
    short = {
        key: [18.0 + index * 0.1 for index in range(MIN_SERIES_SAMPLES - 5)]
        for key in DERIVED_HISTORY_KEYS
    }
    realized = _indicator(model.score(_context_with_derived_series(short)), "realized_vol")

    assert realized.percentile is None
    assert realized.risk_score == 42.0


def test_the_gate_changes_the_score_only_when_it_is_on(
    tmp_path: Any, report: dict[str, Any]
) -> None:
    context = _context_with_derived_series(report["series"])
    off = RiskModel(Settings(_env_file=None)).score(context)
    on = RiskModel(_settings_with_gate(tmp_path, True)).score(context)

    assert off.total_score != on.total_score
    assert 0 <= off.total_score <= 100
    assert 0 <= on.total_score <= 100
