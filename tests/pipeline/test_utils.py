"""Timezone helpers (#94): ET → UTC and earnings session instants."""

from __future__ import annotations

import pytest

from pipeline.utils import earnings_instant, et_instant


class TestEtInstant:
    def test_summer_edt_is_utc_minus_four(self) -> None:
        # 2026-08-12 is EDT (UTC−4): 08:30 ET → 12:30Z.
        assert et_instant("2026-08-12", "08:30") == "2026-08-12T12:30:00Z"

    def test_winter_est_is_utc_minus_five(self) -> None:
        # 2026-12-10 is EST (UTC−5): 14:00 ET → 19:00Z.
        assert et_instant("2026-12-10", "14:00") == "2026-12-10T19:00:00Z"

    def test_dst_transition_is_respected(self) -> None:
        # 2026-03-08 is the first EDT day (spring forward happened 03-08).
        assert et_instant("2026-03-07", "12:00") == "2026-03-07T17:00:00Z"  # EST
        assert et_instant("2026-03-09", "12:00") == "2026-03-09T16:00:00Z"  # EDT

    def test_early_morning_et_release_stays_on_same_utc_date(self) -> None:
        # An 08:30 ET release on a summer day is 12:30Z — same calendar day, so the
        # frontend's local-day grouping never shifts it by a day.
        assert et_instant("2026-08-12", "08:30")[0:10] == "2026-08-12"


class TestEarningsInstant:
    def test_bmo_is_0930_et(self) -> None:
        assert earnings_instant("2026-08-12", "BMO") == "2026-08-12T13:30:00Z"  # EDT

    def test_amc_is_1600_et(self) -> None:
        assert earnings_instant("2026-12-10", "AMC") == "2026-12-10T21:00:00Z"  # EST

    def test_no_session_falls_back_to_noon_utc(self) -> None:
        # FMP stable dropped the session signal (#83): a neutral, unambiguous midday.
        assert earnings_instant("2026-08-12", None) == "2026-08-12T12:00:00Z"

    def test_unknown_session_is_treated_as_none(self) -> None:
        assert earnings_instant("2026-08-12", "time-not-supplied") == "2026-08-12T12:00:00Z"
