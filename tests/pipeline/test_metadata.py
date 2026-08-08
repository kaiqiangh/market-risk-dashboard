"""Scoped quality and honest source timestamp helpers."""

from __future__ import annotations

from pipeline.metadata import latest_row_timestamp, oldest_source_timestamp, quality_for_outcomes
from pipeline.settings import Settings


def test_quality_counts_local_outcomes_only(tmp_path) -> None:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    assert quality_for_outcomes([False, False], settings=settings) == 1.0
    assert quality_for_outcomes([True, False], settings=settings) == 0.8
    assert quality_for_outcomes([True, True], settings=settings) == 0.64


def test_oldest_source_timestamp_is_null_when_any_contributor_is_unknown() -> None:
    assert oldest_source_timestamp(["2026-08-06", "2026-08-05T12:00:00Z"]) == "2026-08-05T12:00:00Z"
    assert oldest_source_timestamp(["2026-08-06", None]) is None
    assert oldest_source_timestamp(["not-a-timestamp"]) is None


def test_latest_row_timestamp_uses_observation_dates_only() -> None:
    rows = [{"date": "2026-08-05", "close": 100}, {"date": "2026-08-06", "close": 101}]
    assert latest_row_timestamp(rows) == "2026-08-06T00:00:00Z"
    assert latest_row_timestamp([{"date": None}]) is None
