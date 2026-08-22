"""Regression tests for the T1 P0 correctness fixes (wayfinder #187).

Covers four review findings:
1. run.py crash handler referenced an unbound results when collection crashed before
   assignment, so the E-5 failure report was silently lost.
2. is_schema_compatible raised IndexError on 1- or 2-part versions instead of failing closed.
3. Published version literals drifted (schema-version.json "1.0.0" vs SCHEMA_VERSION "1.1.0";
   freshness shell "1.1.0" vs METADATA_SCHEMA_VERSION "1.2.0").
4. A future generated_at certified freshness instead of degrading loudly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import pipeline.run as run_mod
from pipeline.schemas.envelope import SCHEMA_VERSION, is_schema_compatible
from pipeline.schemas.metadata import METADATA_SCHEMA_VERSION
from pipeline.storage import StorageWriter
from pipeline.validation.freshness import evaluate_freshness


# ---- 1. crash handler keeps the E-5 failure-report invariant ----


def test_crash_during_collection_still_writes_failure_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_run_collection raising BEFORE results binds must still produce a run-report."""
    artifacts = tmp_path / "artifacts"
    monkeypatch.setattr(run_mod.settings, "artifacts_dir", artifacts)

    def _boom(command: str) -> dict[str, object]:
        raise RuntimeError("collection exploded")

    monkeypatch.setattr(run_mod, "_run_collection", _boom)

    rc = run_mod.main(["--full"])

    assert rc == 1
    reports = list((artifacts / "logs").glob("run-report-*.json"))
    assert len(reports) == 1, "a dead run must leave exactly one failure report"
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert "RuntimeError" in str(report.get("error", ""))


# ---- 2. is_schema_compatible fails closed on truncated versions ----


@pytest.mark.parametrize(
    "bad_version",
    ["1", "1.1", "", "not-a-version", "1.x.0", "1.1.0.9", None],
)
def test_is_schema_compatible_non_canonical_versions_fail_closed(bad_version: object) -> None:
    """Foreign short/over-long/malformed/non-string versions are incompatible - never an
    IndexError or AttributeError (#187 review: over-long slices, None-ish inputs)."""
    assert is_schema_compatible(bad_version, SCHEMA_VERSION) is False  # type: ignore[arg-type]


def test_is_schema_compatible_current_version_accepted() -> None:
    assert is_schema_compatible(SCHEMA_VERSION, SCHEMA_VERSION) is True


def test_is_schema_compatible_same_major_newer_patch_accepted() -> None:
    # Patch is ignored per the documented rules ("1.0.1" case in test_schemas).
    assert is_schema_compatible("1.1.1", SCHEMA_VERSION) is True


# ---- 3. version literals come from the constants, not restated strings ----


def test_write_schema_version_defaults_to_live_schema_version(tmp_path: Path) -> None:
    writer = StorageWriter(tmp_path / "data")
    writer.write_schema_version()
    published = json.loads(
        (tmp_path / "data/metadata/schema-version.json").read_text(encoding="utf-8")
    )
    assert published["schema_version"] == SCHEMA_VERSION


def test_absent_metadata_shells_use_metadata_schema_version(tmp_path: Path) -> None:
    writer = StorageWriter(tmp_path / "data")
    assert writer.read_freshness_raw()["schema_version"] == METADATA_SCHEMA_VERSION
    assert writer.read_sources_raw()["schema_version"] == METADATA_SCHEMA_VERSION


# ---- 4. future timestamps beyond skew tolerance are stale, never fresh ----


def test_future_timestamp_beyond_tolerance_is_stale() -> None:
    now = datetime.now(timezone.utc)
    one_hour_ahead = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert evaluate_freshness(one_hour_ahead, 60, now=now) == "stale"


def test_future_timestamp_within_skew_tolerance_is_fresh() -> None:
    now = datetime.now(timezone.utc)
    one_minute_ahead = (now + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert evaluate_freshness(one_minute_ahead, 60, now=now) == "fresh"


# ---- 5. review fix: a future timestamp's stale verdict names its actual cause ----


def test_finalize_future_timestamp_detail_distinguishes_from_late_fetch() -> None:
    from pipeline.validation.freshness import finalize_freshness

    now = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
    two_hours_ahead = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    verdict = finalize_freshness("macro", two_hours_ahead, False, now=now)
    assert verdict.status == "stale"
    assert "future" in verdict.reason.detail.lower()

    month_old = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mundane = finalize_freshness("macro", month_old, False, now=now)
    assert mundane.status == "stale"
    assert "future" not in mundane.reason.detail.lower()
