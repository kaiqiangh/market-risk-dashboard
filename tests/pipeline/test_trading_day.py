"""Trading-day gate unit tests (ADR-0006).

The closed/open expectations below were verified against exchange_calendars
4.13.2 (XNYS / XSHG). CN 2026 dates reflect the exchange calendar data shipped
by the package (New Year break Jan 1-2, CNY week from Feb 16, National Day
Golden Week from Oct 1); US dates follow statutory holidays and NYSE observed
days (July 4 2026 falls on Saturday -> observed Friday Jul 3).
"""

import datetime as dt

import pytest

from pipeline.schedule.trading_day import is_trading_day, main


@pytest.mark.parametrize(
    ("market", "day", "expected"),
    [
        # New Year's Day 2026 (Thu): both exchanges closed
        ("us", dt.date(2026, 1, 1), False),
        ("cn", dt.date(2026, 1, 1), False),
        # Jan 2 (Fri): NYSE open; SSE still on extended New Year break
        ("us", dt.date(2026, 1, 2), True),
        ("cn", dt.date(2026, 1, 2), False),
        # Weekend: closed for both
        ("us", dt.date(2026, 1, 3), False),
        ("cn", dt.date(2026, 1, 3), False),
        ("us", dt.date(2026, 1, 4), False),
        ("cn", dt.date(2026, 1, 4), False),
        # Monday after the break: open for both
        ("us", dt.date(2026, 1, 5), True),
        ("cn", dt.date(2026, 1, 5), True),
        # Feb 16 (Mon): US Presidents Day AND start of CN CNY break
        ("us", dt.date(2026, 2, 16), False),
        ("cn", dt.date(2026, 2, 16), False),
        # CNY day 1 (Feb 17): SSE closed, NYSE open
        ("us", dt.date(2026, 2, 17), True),
        ("cn", dt.date(2026, 2, 17), False),
        # July 4 2026 = Saturday -> observed Friday Jul 3: US closed, CN open
        ("us", dt.date(2026, 7, 3), False),
        ("cn", dt.date(2026, 7, 3), True),
        # US Labor Day (first Monday of Sept): US closed, CN open
        ("us", dt.date(2026, 9, 7), False),
        ("cn", dt.date(2026, 9, 7), True),
        # CN National Day Golden Week: SSE closed, NYSE open
        ("us", dt.date(2026, 10, 1), True),
        ("cn", dt.date(2026, 10, 1), False),
        # Christmas: US closed, CN open
        ("us", dt.date(2026, 12, 25), False),
        ("cn", dt.date(2026, 12, 25), True),
    ],
)
def test_is_trading_day(market, day, expected):
    assert is_trading_day(market, day) is expected


def test_cli_exit_codes():
    # Trading day -> 0
    assert main(["--market", "us", "--date", "2026-01-02"]) == 0
    # Closed (holiday) -> 3
    assert main(["--market", "us", "--date", "2026-01-01"]) == 3
    assert main(["--market", "cn", "--date", "2026-10-01"]) == 3


def test_fail_open_on_check_error(capsys):
    """A broken check must not block the run: treat as trading day, exit 0."""
    import pipeline.schedule.trading_day as td

    real = td.is_trading_day

    def _boom(market, day=None):
        raise RuntimeError("simulated check failure")

    td.is_trading_day = _boom
    try:
        assert td.main(["--market", "us", "--date", "2026-01-02"]) == 0
    finally:
        td.is_trading_day = real
    err = capsys.readouterr().err
    assert "fail-open" in err
