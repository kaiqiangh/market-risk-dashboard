"""Calibration harness tests (#72 — sign convention + heuristic-fallback labelling).

Previously ZERO coverage for `pipeline/risk/calibration.py`. The harness is a
decision-making tool (does the risk model warn early enough?), so its sign convention
and its honesty about which scoring path it measures are both load-bearing.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.risk.calibration import composite_score, evaluate_segment

REPO_ROOT = Path(__file__).resolve().parents[2]

DATES = [f"2026-01-{d:02d}" for d in range(1, 11)]
# SPX rises to a peak at index 4, then declines (the crash).
SPX_PEAK_AT_4 = [100.0, 102.0, 104.0, 106.0, 108.0, 105.0, 100.0, 95.0, 90.0, 85.0]


def test_lead_time_sign_convention() -> None:
    """AC #1/#72: a score that rises BEFORE the peak yields a POSITIVE lead time.

    The risk score crosses 60 at index 2 (VIX 40 + HY 5.0 + no drawdown yet); the SPX
    peak is at index 4 — the lead time must be +2 days (warned early), not -2.
    """
    vix = [15.0, 30.0, 40.0, 45.0, 50.0, 45.0, 40.0, 35.0, 30.0, 25.0]
    hy = [2.5, 4.0, 5.0, 6.0, 7.0, 6.5, 6.0, 5.5, 5.0, 4.5]

    result = evaluate_segment(DATES, vix, hy, SPX_PEAK_AT_4, "2008")
    lead = result["early_warning_days_vs_peak"]
    assert lead == 2, f"warned 2 days before the peak, got {lead!r}"
    assert lead > 0


def test_late_warning_yields_negative_lead_time() -> None:
    """#72: a score that crosses 60 AFTER the peak yields a NEGATIVE lead time.

    The score stays low through the peak (VIX 15 / HY 2.5) and only crosses 60 at
    index 6 once the drawdown is deep — the lead time must be -2 days (warned late).
    """
    vix = [15.0, 15.0, 15.0, 15.0, 15.0, 20.0, 40.0, 45.0, 50.0, 55.0]
    hy = [2.5, 2.5, 2.5, 2.5, 2.5, 3.0, 5.0, 6.0, 7.0, 7.5]

    result = evaluate_segment(DATES, vix, hy, SPX_PEAK_AT_4, "2008")
    lead = result["early_warning_days_vs_peak"]
    assert lead == -2, f"warned 2 days after the peak, got {lead!r}"
    assert lead < 0


def test_output_labelled_heuristic_fallback() -> None:
    """AC #2/#72: every result carries the heuristic-fallback path label.

    The harness evaluates `heuristic_risk_score` — the FALLBACK path used when percentile
    data is unavailable — NOT the production percentile path in `compute_indicator_score`.
    """
    vix = [15.0, 30.0, 40.0, 45.0, 50.0, 45.0, 40.0, 35.0, 30.0, 25.0]
    hy = [2.5, 4.0, 5.0, 6.0, 7.0, 6.5, 6.0, 5.5, 5.0, 4.5]

    result = evaluate_segment(DATES, vix, hy, SPX_PEAK_AT_4, "2008")
    assert result["scoring_path"] == "heuristic_fallback", (
        "the harness must label every output as the heuristic fallback path, "
        f"got {result['scoring_path']!r}"
    )
    # The composite score is itself built from the heuristic table.
    assert composite_score(25.0, 5.0, -10.0) is not None


def test_published_artifacts_unaffected() -> None:
    """AC: running the harness writes nothing under public/data (#72)."""
    public_data = REPO_ROOT / "public" / "data"

    def snapshot() -> set[str]:
        return {p.relative_to(public_data).as_posix() for p in public_data.rglob("*") if p.is_file()}

    before = snapshot()
    vix = [15.0, 30.0, 40.0, 45.0, 50.0, 45.0, 40.0, 35.0, 30.0, 25.0]
    hy = [2.5, 4.0, 5.0, 6.0, 7.0, 6.5, 6.0, 5.5, 5.0, 4.5]
    evaluate_segment(DATES, vix, hy, SPX_PEAK_AT_4, "2008")
    composite_score(25.0, 5.0, -10.0)
    assert snapshot() == before, "the calibration harness must not write under public/data"


def test_report_legend_matches_numbers() -> None:
    """#72 ruling (a): the report legend agrees with positive-means-early.

    The table reports `34 days (before peak)` / `7 days (before peak)` as positive; the
    legend must say positive = warned before the peak, never negative. A text pin so the
    false claim cannot silently flip back.
    """
    text = (REPO_ROOT / "docs" / "calibration-report.md").read_text(encoding="utf-8")
    assert "positive = warning before the peak" in text.lower() or "positive = warned before the peak" in text.lower()
    assert "negative = warning before the peak" not in text.lower()
    assert "negative = warned before peak" not in text.lower()
    # The scope must say the harness evaluates the heuristic FALLBACK path, not production.
    assert "heuristic fallback" in text.lower() or "fallback" in text.lower()
