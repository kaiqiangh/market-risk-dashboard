"""#93 theme-series math: percentile_of_trailing_return + chain_equal_weight_daily (#86 §4).

Pins: the percentile ranks a trailing-20-session RETURN against its own 1y distribution (not
a price level), `obs` carries the true count below min_obs, and the equal-weight basket chain
renormalizes members missing on a date.
"""

from __future__ import annotations

from pipeline.indicators.themes import (
    chain_equal_weight_daily,
    changes_from_closes,
    percentile_of_trailing_return,
)


def test_percentile_of_trending_series_is_not_stuck_at_100() -> None:
    """#86 §4.1: a rising price with noisy returns must NOT sit at ~100 — the percentile
    ranks the trailing *return* against its own 1y return distribution, so a normal day is
    mid-distribution, not the max (price-level ranking is the rejected bug)."""
    import random

    random.seed(7)
    closes = [100.0]
    for _ in range(300):
        closes.append(closes[-1] * (1.0 + 0.001 + random.uniform(-0.006, 0.006)))
    percentile, obs = percentile_of_trailing_return(closes, window=20, lookback=252, min_observations=100)
    assert obs >= 100
    assert percentile is not None and 5 < percentile < 95, percentile


def test_percentile_near_100_when_trailing_return_is_the_best() -> None:
    """A series whose last-20-session return is the best in its year ranks near the top."""
    closes = [100.0 + i * 0.5 for i in range(232)]  # 232 sessions of slow climb (~8.7% per 20)
    closes += [closes[-1] * (1.02 ** (k + 1)) for k in range(20)]  # then +2%/session → ~48% r20
    percentile, obs = percentile_of_trailing_return(closes, window=20, lookback=252, min_observations=100)
    assert obs >= 100
    assert percentile is not None and percentile > 90, percentile


def test_below_min_obs_returns_none_with_true_count() -> None:
    """#86 §4.3: obs < min_observations → percentile None but obs carries the true count."""
    closes = [100.0 + i for i in range(60)]  # 60 bars → ~40 window returns
    percentile, obs = percentile_of_trailing_return(closes, window=20, lookback=252, min_observations=100)
    assert percentile is None
    assert obs < 100


def test_chain_equal_weight_renormalizes_missing_members() -> None:
    """Members missing on a date are renormalized away; the chain still moves."""
    rows_a = [{"date": f"2026-0{i}-01", "close": 100.0 + i} for i in range(1, 6)]  # 5 dates
    rows_b = [{"date": "2026-01-02", "close": 50.0}, {"date": "2026-01-04", "close": 52.0}]  # gaps
    index = chain_equal_weight_daily({"A": rows_a, "B": rows_b})
    assert len(index) >= 4
    closes = [r["close"] for r in index]
    # The index is a proper chain (no NaN/flat fabrication), first close = 100.0.
    assert closes[0] == 100.0
    assert all(c > 0 for c in closes)


def test_changes_from_closes_session_offsets() -> None:
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
    c1d, c1w, c1m = changes_from_closes(closes)
    assert c1d == 0.9524  # (106/105 - 1) * 100
    assert c1w == 6.0  # (106/100 - 1) * 100 (6 sessions back)
    assert c1m is None  # honest: fewer than 21 sessions — no fabricated "1M"
