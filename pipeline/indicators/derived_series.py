"""Derived value series for the computed risk indicators (D3).

Why this exists
---------------
`pipeline/risk/scoring.compute_indicator_score` has two paths: a **percentile** path against a
per-indicator value history, and a **heuristic** fallback against a hand-drawn mapping table.
Only nine indicators have a history — the FRED series. The other ten are single point values
recomputed each run from the collected market histories, so they can only ever be scored by the
table; and three of them (`cross_asset_confirmation`, `small_cap_relative`, `semis_relative`)
are not in the table at all, so they are scored at the constant fallback 50.0 every single day.

This module derives the missing value histories from data the pipeline **already collects**:
the daily closes of the benchmark proxies (SPY / IWM / SOXX, `INDEX_HISTORIES`) and the symbol
universe `breadth_snapshot` already walks. It makes no provider call.

Scope and honesty rules
-----------------------
- **Feasibility is checked before computing.** A series that cannot reach
  :data:`MIN_SERIES_SAMPLES` observations with the available calendar is reported as
  ``insufficient_history`` rather than partially computed. On the current 1y target window
  this withholds `price_vs_ma200` and `breadth_above_ma200` (both need a 200-session
  lookback → 51 observations, vs 187 for the 63-session keys).
- **A series is never derived on a different definition than the live value.** The cross-asset
  confirmation is a hit rate over eight signals; deriving it from the five signals whose
  history exists would silently change what the number means, so it is withheld with the
  missing inputs named (:func:`cross_asset_series_requirement`).
- **As-of alignment.** Point-in-time value at date *d* uses only closes dated ≤ *d*, so a
  derived series cannot leak a future observation into an earlier score (the same boundary
  `pipeline/risk/calibration.py` enforces).
- **Cost.** The universe-wide series rebuild an as-of frame per benchmark date, so they are the
  expensive part — one reason the caller opts in via ``scoring.derived_history.enabled``. The
  gate's primary reason is that moving an input off the heuristic table changes published
  scores; cost only decides how eagerly it is computed.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.indicators.breadth import breadth_above_ma200, new_highs_lows
from pipeline.indicators.technical import (
    distance_from_ma,
    drawdown_52w,
    momentum,
    realized_vol,
)

#: Benchmark whose calendar defines the derived series' dates, and whose closes back the
#: volatility/trend indicators (same symbol `trend_snapshot` defaults to).
DEFAULT_BENCHMARK = "SPY"

#: Symbols behind the relative-strength indicators (`breadth.relative_strength` benchmarks
#: against SPY, lookback 63).
RELATIVE_TARGETS: dict[str, str] = {"small_cap_relative": "IWM", "semis_relative": "SOXX"}

#: Mirrors `pipeline.risk.scoring.MIN_HISTORY_SAMPLES`: below this the derived series would be
#: rejected by the percentile path anyway, so it is withheld rather than published.
MIN_SERIES_SAMPLES = 60


@dataclass(frozen=True)
class SeriesSpec:
    """One derivable indicator series and the lookback a single observation needs."""

    key: str
    lookback: int
    description: str


#: The derivable computed indicators. `lookback` is in benchmark sessions: an observation at
#: date *d* exists only when at least this many sessions are available up to *d*.
SERIES_SPECS: tuple[SeriesSpec, ...] = (
    SeriesSpec("realized_vol", 21, "benchmark 20-session annualized realized volatility"),
    SeriesSpec("drawdown_52w", 1, "benchmark drawdown from the trailing 52-week high"),
    SeriesSpec("momentum_3m", 64, "benchmark 63-session momentum"),
    SeriesSpec("price_vs_ma200", 200, "benchmark distance from its 200-session moving average"),
    SeriesSpec("small_cap_relative", 64, "IWM minus SPY 63-session relative strength"),
    SeriesSpec("semis_relative", 64, "SOXX minus SPY 63-session relative strength"),
    SeriesSpec("new_highs_ratio", 64, "share of the universe at a 63-session high"),
    SeriesSpec("new_lows_ratio", 64, "share of the universe at a 63-session low"),
    SeriesSpec("breadth_above_ma200", 200, "share of the universe above its 200-session MA"),
)

#: Universe-wide specs (iterated over every history in the ctx, like `breadth_snapshot`).
UNIVERSE_KEYS: frozenset[str] = frozenset(
    {"new_highs_ratio", "new_lows_ratio", "breadth_above_ma200"}
)

#: The eight production cross-asset signals and the input each one needs (ADR: the confirmation
#: is a hit rate over exactly these; a partial replay is a different statistic).
CROSS_ASSET_SIGNAL_INPUTS: dict[str, tuple[str, str]] = {
    "spy_down": ("market", "SPY"),
    "hy_oas_widening": ("macro_series", "bamlh0a0hym2"),
    "dollar_strength": ("macro_series", "dtwexbgs"),
    "real_rate_pressure": ("macro_series", "dfii10"),
    "bitcoin_down": ("market", "BTC-USD"),
    "small_cap_underperformance": ("market", "IWM"),
    "copper_down": ("market", "HG=F"),
    "gold_up": ("market", "GC=F"),
}


def _closes_index(rows: Sequence[dict[str, Any]]) -> tuple[list[str], list[float]]:
    """(ascending dates, closes) for one symbol, dropping rows without a finite close."""
    dates: list[str] = []
    closes: list[float] = []
    for row in rows or []:
        close = row.get("close")
        if isinstance(close, (int, float)) and not isinstance(close, bool):
            dates.append(str(row.get("date", "")))
            closes.append(float(close))
    return dates, closes


def _as_of(dates: Sequence[str], closes: Sequence[float], target_date: str) -> list[float]:
    """Closes dated at or before ``target_date`` (point-in-time slice)."""
    return list(closes[: bisect_right(dates, target_date)])


def series_feasibility(histories: dict[str, list[dict[str, Any]]], spec: SeriesSpec) -> int:
    """How many observations the series would have, from the benchmark calendar length.

    Returns 0 when the benchmark is absent. The count is the theoretical maximum
    (``calendar - lookback``); universe-wide keys can be shorter when few symbols carry enough
    history, and `derive_report` reports the realised count separately.
    """
    dates, _ = _closes_index(histories.get(DEFAULT_BENCHMARK) or [])
    return max(0, len(dates) - spec.lookback)


def derive_series(histories: dict[str, list[dict[str, Any]]]) -> dict[str, list[float]]:
    """Derive every feasible indicator series from the collected histories.

    Returns ``{indicator_key: [values ascending by date]}`` containing only series long enough
    for the percentile path. Infeasible keys are absent — call :func:`derive_report` for the
    reason, because a silently missing series is the defect this module exists to remove.
    """
    return derive_report(histories)["series"]


def derive_report(
    histories: dict[str, list[dict[str, Any]]],
    series_history: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Derive the series and report, per key, what was produced and what was withheld.

    ``histories`` is the symbol → rows market history the risk context carries;
    ``series_history`` is the FRED series history it carries alongside. The latter is needed by
    one sub-report only — the cross-asset confirmation hit rate is backed by macroeconomic
    inputs as well as market ones, and calling them missing because this argument was omitted
    would be a false statement about the data.

    ``withheld`` maps an indicator key to ``{"reason", ...}``, where ``reason`` is one of

    - ``no_source`` — an input symbol is not in the collected histories at all (the benchmark,
      or the small-cap/semis relative target);
    - ``insufficient_history`` — the inputs are present but too short for the percentile path:
      the feasible observation count is below `MIN_SERIES_SAMPLES`;
    - ``partial_signal_coverage`` — the live value is an aggregate over more inputs than the
      collected histories carry, so a replay would be a different statistic;
    - ``not_implemented`` — every input is present and the series is derivable in principle,
      but no derivation is wired up yet (the cross-asset hit rate).

    A key is present in ``series`` if and only if a derivation ran and produced enough
    observations, so a silently missing series cannot be mistaken for a zero.
    """
    histories = histories or {}
    benchmark_dates, benchmark_closes = _closes_index(histories.get(DEFAULT_BENCHMARK) or [])
    universe = {
        symbol: _closes_index(rows)
        for symbol, rows in histories.items()
        if rows
    }

    series: dict[str, list[float]] = {}
    observed: dict[str, dict[str, Any]] = {}
    withheld: dict[str, dict[str, Any]] = {}
    universe_frames: list[tuple[str, dict[str, list[dict[str, Any]]]]] | None = None

    for spec in SERIES_SPECS:
        target = RELATIVE_TARGETS.get(spec.key)
        if not benchmark_dates:
            withheld[spec.key] = _no_source(
                spec, f"benchmark {DEFAULT_BENCHMARK!r} is not in the collected histories"
            )
            continue
        if target is not None and not (universe.get(target) or ([], []))[0]:
            withheld[spec.key] = _no_source(
                spec, f"relative symbol {target!r} is not in the collected histories"
            )
            continue
        feasible = series_feasibility(histories, spec)
        if feasible < MIN_SERIES_SAMPLES:
            withheld[spec.key] = _insufficient(
                spec,
                feasible,
                f"needs {spec.lookback} benchmark sessions of lookback plus "
                f"{MIN_SERIES_SAMPLES} observations; the benchmark carries "
                f"{len(benchmark_dates)}",
            )
            continue
        if target is not None:
            values = _relative_series(histories, benchmark_dates, spec, target)
        elif spec.key in UNIVERSE_KEYS:
            if universe_frames is None:
                universe_frames = _universe_frames(universe, benchmark_dates)
            values = _universe_series(universe_frames, spec.key)
        else:
            values = _benchmark_series(benchmark_closes, benchmark_dates, spec.key)
        if len(values) < MIN_SERIES_SAMPLES:
            withheld[spec.key] = _insufficient(
                spec,
                len(values),
                "the realised observations fell below the percentile-path minimum "
                "(a thin universe sample can leave a universe-wide series short)",
            )
            continue
        series[spec.key] = values
        observed[spec.key] = {
            "observations": len(values),
            "lookback_sessions": spec.lookback,
            "description": spec.description,
            "first_date": benchmark_dates[-len(values)] if len(values) <= len(benchmark_dates) else None,
            "last_date": benchmark_dates[-1],
        }

    withheld["cross_asset_confirmation"] = cross_asset_series_requirement(
        histories, series_history
    )

    return {
        "benchmark": DEFAULT_BENCHMARK,
        "benchmark_observations": len(benchmark_dates),
        "universe_symbols": sum(1 for dates, _ in universe.values() if dates),
        "series": series,
        "observed": observed,
        "withheld": withheld,
        "derived_keys": sorted(series),
    }


def _no_source(spec: SeriesSpec, detail: str) -> dict[str, Any]:
    return {"reason": "no_source", "description": spec.description, "detail": detail}


def _insufficient(spec: SeriesSpec, observations: int, detail: str) -> dict[str, Any]:
    return {
        "reason": "insufficient_history",
        "description": spec.description,
        "observations": observations,
        "required_observations": MIN_SERIES_SAMPLES,
        "lookback_sessions": spec.lookback,
        "detail": detail,
    }


def _benchmark_series(
    benchmark_closes: Sequence[float], benchmark_dates: Sequence[str], key: str
) -> list[float]:
    """One benchmark-derived series, computed as-of each date (no future leakage)."""
    values: list[float] = []
    for index in range(len(benchmark_closes)):
        window = list(benchmark_closes[: index + 1])
        if key == "realized_vol":
            value = realized_vol(window, 20)
        elif key == "momentum_3m":
            value = momentum(window, 63)
        elif key == "drawdown_52w":
            value = drawdown_52w(window)
        elif key == "price_vs_ma200":
            value = distance_from_ma(window, 200)
        else:  # pragma: no cover - SERIES_SPECS is the only caller and is exhaustive
            raise ValueError(f"no benchmark derivation for {key!r}")
        if value is not None:
            values.append(float(value))
    return values


def _relative_series(
    histories: dict[str, list[dict[str, Any]]],
    benchmark_dates: Sequence[str],
    spec: SeriesSpec,
    target: str,
) -> list[float]:
    """Relative-strength series: `breadth.relative_strength` evaluated as-of each date.

    The live value uses the same function on the same 1y frames, so the series and the current
    observation are the same statistic at different dates — the property that makes a
    percentile window meaningful.
    """
    target_dates, target_closes = _closes_index(histories.get(target) or [])
    bench_dates, bench_closes = _closes_index(histories.get(DEFAULT_BENCHMARK) or [])
    if not target_dates or not bench_dates:
        return []
    lookback = spec.lookback - 1  # relative_strength's `lookback` counts sessions, not bars
    values: list[float] = []
    for date in benchmark_dates:
        target_window = _as_of(target_dates, target_closes, date)
        bench_window = _as_of(bench_dates, bench_closes, date)
        if len(target_window) <= lookback or len(bench_window) <= lookback:
            continue
        target_return = (target_window[-1] - target_window[-lookback - 1]) / target_window[-lookback - 1]
        bench_return = (bench_window[-1] - bench_window[-lookback - 1]) / bench_window[-lookback - 1]
        values.append(round((target_return - bench_return) * 100.0, 4))
    return values


def _universe_frames(
    universe: dict[str, tuple[list[str], list[float]]],
    benchmark_dates: Sequence[str],
) -> list[tuple[str, dict[str, list[dict[str, Any]]]]]:
    """One as-of frame per benchmark date, shared by every universe-wide series.

    Building a frame is O(symbols × the sessions up to that date), so it is done once and
    reused across `UNIVERSE_KEYS` instead of once per key. Dropping a symbol whose history
    starts after the frame date keeps `breadth_snapshot`'s "not yet observable" boundary.
    """
    frames: list[tuple[str, dict[str, list[dict[str, Any]]]]] = []
    for date in benchmark_dates:
        frames.append(
            (
                date,
                {
                    symbol: [
                        {"date": dates[index], "close": closes[index]}
                        for index in range(bisect_right(dates, date))
                    ]
                    for symbol, (dates, closes) in universe.items()
                    if dates and dates[0] <= date
                },
            )
        )
    return frames


def _universe_series(
    frames: Sequence[tuple[str, dict[str, list[dict[str, Any]]]]],
    key: str,
) -> list[float]:
    """One universe-wide breadth series, computed from the shared as-of frames."""
    values: list[float] = []
    for _, frame in frames:
        if key == "breadth_above_ma200":
            ratio = breadth_above_ma200(frame)["ratio"]
        else:
            counts = new_highs_lows(frame)
            ratio = counts["new_highs"] if key == "new_highs_ratio" else counts["new_lows"]
        if ratio is not None:
            values.append(float(ratio))
    return values


def cross_asset_series_requirement(
    histories: dict[str, list[dict[str, Any]]],
    series_history: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Report whether the 8-signal cross-asset confirmation could be replayed as a series.

    The live confirmation is a hit rate over eight signals. A series built from fewer signals
    is a *different statistic*, so this never returns a partial series: it names the missing
    inputs instead. Today that is the gold/copper/bitcoin history — gold and copper reach the
    calibration panel but not the live risk target set, and bitcoin has no daily history at all.

    ``derivable`` states whether the inputs are there (a property of the data), separately from
    ``reason``, which states why no series was produced (which can also be that no derivation
    is implemented yet). Collapsing the two would let "the data is complete" read as "a series
    exists".
    """
    macro_series = {str(key).lower() for key in (series_history or {})}
    market = {symbol for symbol, rows in (histories or {}).items() if rows}
    missing: list[str] = []
    for signal, (source, name) in CROSS_ASSET_SIGNAL_INPUTS.items():
        available = name in market if source == "market" else name in macro_series
        if not available:
            missing.append(f"{signal}:{name}")
    return {
        "derivable": not missing,
        "reason": "partial_signal_coverage" if missing else "not_implemented",
        "description": "8-signal production cross-asset confirmation hit rate",
        "observed_signals": len(CROSS_ASSET_SIGNAL_INPUTS) - len(missing),
        "required_signals": len(CROSS_ASSET_SIGNAL_INPUTS),
        "missing_inputs": missing,
        "detail": (
            f"the live value is a hit rate over {len(CROSS_ASSET_SIGNAL_INPUTS)} signals "
            f"(a level-vs-threshold test per input, not a single series); a replay would cover "
            f"{len(CROSS_ASSET_SIGNAL_INPUTS) - len(missing)} and no hit-rate series is "
            "implemented yet"
        ),
    }
