"""Weight audit tests: static concentration, scoring-path coverage, variance decomposition."""

from __future__ import annotations

import pytest

from pipeline.risk.weight_audit import (
    MAX_SINGLE_INDICATOR_SHARE,
    audit,
    blocking_findings,
    configured_indicator_weights,
    dimension_stats,
    render,
    score_path_coverage,
    scoring_path,
    variance_decomposition,
    weight_concentration,
)
from pipeline.settings import Settings

#: A minimal two-dimension model: one live percentile indicator, one unmapped constant.
_TINY_MODEL = {
    "dimensions": {"a": {"weight": 60}, "b": {"weight": 40}},
    "indicators": {
        "a": [{"key": "vix", "weight": 3}],
        "b": [{"key": "not_a_configured_rule", "weight": 1}],
    },
}


def test_scoring_path_resolves_each_input_to_its_rule() -> None:
    assert scoring_path("vix") == "percentile"  # has a 5Y history series
    assert scoring_path("realized_vol") == "heuristic"  # rule only, no independent series
    # No rule and no series: the key carries weight but is scored at the constant fallback on
    # every run. Update this assertion when a mapping is added (see
    # docs/global-risk-score-weight-review-2026-10-08.md).
    assert scoring_path("cross_asset_confirmation") == "unmapped"


def test_configured_indicator_weights_normalize_within_each_dimension() -> None:
    weights = configured_indicator_weights(_TINY_MODEL)
    by_key = {item.key: item for item in weights}

    assert round(sum(item.global_weight for item in weights), 4) == 100.0
    assert by_key["vix"].global_weight == 60.0
    assert by_key["not_a_configured_rule"].global_weight == 40.0


def test_configured_indicator_weights_use_indicator_share_not_raw_weight() -> None:
    """A dimension spanning several indicators splits its weight by indicator share."""
    model = {
        "dimensions": {"a": {"weight": 20}},
        "indicators": {"a": [{"key": "hy_oas", "weight": 10}, {"key": "vix", "weight": 10}]},
    }
    weights = configured_indicator_weights(model)

    assert [item.global_weight for item in weights] == [10.0, 10.0]


def test_weight_concentration_reads_even_and_single_extremes() -> None:
    even = weight_concentration([1.0, 1.0, 1.0, 1.0])
    single = weight_concentration([1.0, 0.0, 0.0, 0.0])

    assert even["hhi"] == even["equal_hhi"] == 0.25
    assert even["effective_n"] == 4.0
    assert single["hhi"] == 1.0
    assert single["effective_n"] == 1.0
    assert single["top3_share"] == 1.0


def test_score_path_coverage_separates_live_from_constant_weight() -> None:
    coverage = score_path_coverage(configured_indicator_weights(_TINY_MODEL))

    assert coverage["by_path"]["percentile"]["global_weight"] == 60.0
    assert coverage["by_path"]["unmapped"]["global_weight"] == 40.0
    assert coverage["unmapped_keys"] == ["not_a_configured_rule"]
    # The unmapped half contributes a fixed 50.0 × 40 / 100 points to every score.
    assert coverage["dead_weight"] == 40.0
    assert coverage["dead_points"] == 20.0
    assert coverage["total_global_weight"] == 100.0


def test_dimension_stats_flag_a_pinned_dimension() -> None:
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 50.0, "b": 40.0}},
        {"total_score": 52.0, "dim_scores": {"a": 50.0, "b": 60.0}},
    ]
    stats = {item["key"]: item for item in dimension_stats(rows)}

    assert stats["a"]["unique"] == 1
    assert stats["a"]["non_responsive"] is True
    assert stats["a"]["std"] == 0.0
    assert stats["b"]["non_responsive"] is False
    assert stats["b"]["range"] == 20.0


def test_variance_decomposition_attributes_movement_to_the_moving_dimension() -> None:
    model = {"dimensions": {"a": {"weight": 50}, "b": {"weight": 50}}, "indicators": {}}
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 40.0, "b": 60.0}},
        {"total_score": 55.0, "dim_scores": {"a": 50.0, "b": 60.0}},
        {"total_score": 60.0, "dim_scores": {"a": 60.0, "b": 60.0}},
    ]
    decomposition = variance_decomposition(rows, model)
    shares = {item["key"]: item["variance_share"] for item in decomposition["dimensions"]}

    assert shares["a"] == 1.0
    assert shares["b"] == 0.0
    assert decomposition["residual_mean_abs"] == 0.0
    assert decomposition["residual_max_abs"] == 0.0
    assert decomposition["observations"] == 3


def test_variance_decomposition_reports_a_counter_moving_dimension_as_negative() -> None:
    model = {"dimensions": {"a": {"weight": 50}, "b": {"weight": 50}}, "indicators": {}}
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 40.0, "b": 60.0}},
        {"total_score": 55.0, "dim_scores": {"a": 60.0, "b": 50.0}},
        {"total_score": 60.0, "dim_scores": {"a": 80.0, "b": 40.0}},
    ]
    shares = {
        item["key"]: item["variance_share"]
        for item in variance_decomposition(rows, model)["dimensions"]
    }

    assert shares["a"] > 0
    assert shares["b"] < 0  # it diversified the total instead of driving it


def test_variance_decomposition_discloses_the_renormalization_residual() -> None:
    """A day whose applied weights differ from the config shows up as a non-zero residual."""
    model = {"dimensions": {"a": {"weight": 50}, "b": {"weight": 50}}, "indicators": {}}
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 40.0, "b": 60.0}},
        {"total_score": 88.0, "dim_scores": {"a": 40.0, "b": 60.0}},  # weight was redistributed
    ]
    decomposition = variance_decomposition(rows, model)

    # Row 1 reconstructs exactly (0); row 2 is off by 38 — reported as a mean over both rows,
    # with the spike visible as the max (that is the day a dimension's weight was redistributed).
    assert decomposition["residual_mean_abs"] == 19.0
    assert decomposition["residual_max_abs"] == 38.0


def test_variance_decomposition_handles_a_non_varying_total() -> None:
    model = {"dimensions": {"a": {"weight": 100}}, "indicators": {}}
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 50.0}},
        {"total_score": 50.0, "dim_scores": {"a": 50.0}},
    ]
    decomposition = variance_decomposition(rows, model)

    assert decomposition["dimensions"][0]["variance_share"] is None
    assert decomposition["residual_mean_abs"] == 0.0
    assert "note" in decomposition


def test_audit_separates_findings_from_measurement() -> None:
    rows = [
        {"total_score": 50.0, "dim_scores": {"a": 50.0, "b": 50.0, "trend": 50.0}},
        {"total_score": 60.0, "dim_scores": {"a": 70.0, "b": 50.0, "trend": 50.0}},
    ]
    report = audit(_TINY_MODEL, rows)
    codes = {item["code"] for item in report["findings"]}

    assert "unmapped_indicators" in codes
    assert report["score_path_coverage"]["dead_points"] == 20.0
    assert blocking_findings(report) == [report["findings"][0]]
    assert blocking_findings(report)[0]["severity"] == "high"


def test_audit_flags_a_single_indicator_dimension_over_the_share_cap() -> None:
    report = audit(_TINY_MODEL, [])
    codes = {item["code"] for item in report["findings"]}
    weights = [item for item in report["indicator_weights"] if item["global_weight"] > 10.0]

    assert "single_indicator_dimension" in codes
    assert MAX_SINGLE_INDICATOR_SHARE == 0.10
    assert len(weights) == 2  # both dimensions are one-indicator by construction


def test_render_names_the_dead_weight_and_the_scoring_paths() -> None:
    text = render(audit(_TINY_MODEL, []))

    assert "dead weight" in text
    assert "unmapped" in text
    assert "not_a_configured_rule" in text


def test_shipped_config_is_fully_attributed_across_scoring_paths() -> None:
    """The live config must account for exactly 100 points, however they are split."""
    report = audit(Settings().load_risk_model(), [])
    coverage = report["score_path_coverage"]

    assert coverage["total_global_weight"] == 100.0
    # Per-indicator shares are rounded for readability, so the path buckets can drift by a
    # rounding step; the point is that every point of weight is attributed to *some* path.
    assert sum(
        coverage["by_path"][path]["global_weight"] for path in coverage["by_path"]
    ) == pytest.approx(100.0, abs=0.01)
    assert coverage["dead_points"] == round(coverage["dead_weight"] * 0.5, 4)
    assert coverage["by_path"]["percentile"]["count"] > 0
