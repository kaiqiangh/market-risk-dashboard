"""Theme series math (#93/#86 §4): basket chaining and the trailing-return percentile.

Pure functions, no I/O — the collector fetches the closes and hands them to these.

- :func:`percentile_of_trailing_return` — rank the theme's trailing ``window``-session return
  against the overlapping window returns inside its trailing ``lookback`` sessions. This is
  deliberately NOT a price-level rank (the `percentile_in_window` bug, #86 §4.1) and NOT a
  cross-sectional constituent rank.
- :func:`chain_equal_weight_daily` — build one equal-weight daily-return index from per-symbol
  close series (members missing on a date are renormalized away), so card numbers and the
  percentile provably describe the same object (#86 §4.5).
"""

from __future__ import annotations

from typing import Any


def percentile_of_trailing_return(
    closes: list[float],
    window: int = 20,
    lookback: int = 252,
    min_observations: int = 100,
) -> tuple[float | None, int]:
    """Return ``(percentile_1y, obs)`` for the trailing ``window``-session return.

    ``obs`` is the number of overlapping window returns inside ``lookback`` sessions. Below
    ``min_observations`` the percentile is ``None`` (the estimate is too coarse to be honest —
    #86 §4.3) but ``obs`` carries the true count so the UI can render "warming up".
    """
    if len(closes) < window + 1:
        return None, 0
    window_returns: list[float] = []
    for i in range(len(closes) - 1, max(-1, len(closes) - 1 - lookback), -1):
        if i - window >= 0 and closes[i - window]:
            window_returns.append(closes[i] / closes[i - window] - 1.0)
    if not window_returns:
        return None, 0
    obs = len(window_returns)
    current = window_returns[0]  # the trailing (most recent) window return
    percentile = sum(1 for r in window_returns if r <= current) / obs * 100.0
    if obs < min_observations:
        return None, obs
    return round(percentile, 1), obs


def chain_equal_weight_daily(series_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Chain an equal-weight daily-return index from per-symbol OHLCV rows.

    ``series_by_symbol``: symbol → rows ``[{date, close}, …]`` (the collector's 1y histories).
    Each date's index move is the mean daily return of the members that traded on both that
    date and the previous trading date; members absent on a date are renormalized away
    (``min_members_present`` semantics, #86 §4). Returns index rows ``[{date, close}]``.

    The index starts at 100.0 on its first observed date; dates on which no member traded are
    skipped (no fabricated flat bars).
    """
    by_date: dict[str, dict[str, float]] = {}
    for symbol, rows in series_by_symbol.items():
        by_date[symbol] = {str(r["date"]): float(r["close"]) for r in rows if r.get("close") is not None}
    if not by_date:
        return []
    dates = sorted({d for member in by_date.values() for d in member})
    if len(dates) < 2:
        return [{"date": dates[0], "close": 100.0}]

    rows: list[dict[str, Any]] = []
    index = 100.0
    for i, date in enumerate(dates):
        if i == 0:
            rows.append({"date": date, "close": index})
            continue
        prev_date = dates[i - 1]
        returns: list[float] = []
        for symbol, member in by_date.items():
            current = member.get(date)
            previous = member.get(prev_date)
            if current is not None and previous:
                returns.append(current / previous - 1.0)
        if not returns:
            continue  # no member traded on this date — skip rather than fabricate a flat bar
        index *= 1.0 + sum(returns) / len(returns)
        rows.append({"date": date, "close": round(index, 4)})
    return rows


def changes_from_closes(closes: list[float]) -> tuple[float | None, float | None, float | None]:
    """(change_1d, change_1w, change_1m) percent from a close series (session offsets 1/6/21)."""
    if len(closes) < 2:
        return None, None, None

    def pct(offset: int) -> float | None:
        prev = closes[-1 - offset] if len(closes) > offset else closes[0]
        if not prev:
            return None
        return round((closes[-1] / prev - 1.0) * 100.0, 4)

    return pct(1), pct(6), pct(21)
