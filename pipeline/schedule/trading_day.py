"""Trading-day gate for market-sensitive automations (ADR-0006).

Usage:
    python -m pipeline.schedule.trading_day --market cn|us [--date YYYY-MM-DD]

Exit codes (machine-readable contract for automation prompts):
    0  `day` is a trading day on the requested exchange
       (also returned when the check itself cannot run — fail-open, see below)
    3  `day` is NOT a trading day on the requested exchange (weekend or exchange holiday)

Fail-open policy (ADR-0006): an extra unattended pipeline run is benign; a wrongly
skipped run is a data gap. Any error in the check (missing dependency, unknown
calendar, bad input) is therefore reported on stderr and exits 0 so the caller
proceeds rather than silently dropping a run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

_EXIT_TRADING = 0
_EXIT_CLOSED = 3

# market key -> exchange_calendars calendar name
_CALENDARS = {
    "us": "XNYS",  # New York Stock Exchange
    "cn": "XSHG",  # Shanghai Stock Exchange
}


def is_trading_day(market: str, day: dt.date | None = None) -> bool:
    """True when `day` is a session on the exchange for `market`.

    Raises on any error — callers implement fail-open by treating a raised
    check as "trading day".
    """
    day = day or dt.date.today()
    # Imported locally: the exchange_calendars package is heavy to load and is
    # only needed by the gate, never by the pipeline itself.
    import exchange_calendars as xcals

    cal = xcals.get_calendar(_CALENDARS[market])
    return bool(cal.is_session(day))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trading-day gate for market-sensitive automations (ADR-0006)"
    )
    parser.add_argument(
        "--market",
        required=True,
        choices=sorted(_CALENDARS),
        help="us = NYSE (XNYS), cn = SSE (XSHG)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="ISO date to test (default: today, Dublin local)",
    )
    args = parser.parse_args(argv)

    try:
        day = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
        trading = is_trading_day(args.market, day)
    except Exception as exc:  # fail-open: never block an unattended run on a check bug
        print(
            f"[trading_day] check failed, treating as trading day (fail-open): {exc}",
            file=sys.stderr,
        )
        return _EXIT_TRADING

    if trading:
        print(
            f"[trading_day] {args.market} ({_CALENDARS[args.market]}): {day.isoformat()} is a trading day"
        )
        return _EXIT_TRADING
    print(
        f"[trading_day] {args.market} ({_CALENDARS[args.market]}): {day.isoformat()} is CLOSED (weekend or exchange holiday)"
    )
    return _EXIT_CLOSED


if __name__ == "__main__":
    sys.exit(main())
