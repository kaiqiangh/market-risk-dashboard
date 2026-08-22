"""Tests for the backfill chain fixes (#188): --days threading, period mapping,
backfill_metadata hardening, and the shared row-count helper."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.metadata import row_count_for
from pipeline.schemas import registry
from pipeline.schemas.envelope import SCHEMA_VERSION
from scripts import backfill as backfill_script
from scripts import backfill_metadata as bfm


# ---- period mapping ----


@pytest.mark.parametrize(
    ("days", "period"),
    [
        (1, "1mo"),
        (30, "1mo"),
        (35, "1mo"),
        (36, "3mo"),
        (90, "3mo"),
        (100, "3mo"),
        (101, "6mo"),
        (200, "6mo"),
        (201, "1y"),
        (3650, "1y"),
    ],
)
def test_period_for_days_maps_window_to_coarsest_covering_period(days: int, period: str) -> None:
    from pipeline.run import _period_for_days

    assert _period_for_days(days) == period


def test_backfill_cli_threads_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI window reaches run_backfill; the public seam is used, not underscore API."""
    captured: list[int] = []
    monkeypatch.setattr(backfill_script, "run_backfill", lambda days: captured.append(days) or 0)
    assert backfill_script.main(["--days", "45"]) == 0
    assert captured == [45]
    assert backfill_script.main([]) == 0
    assert captured == [45, 90]  # default


def test_run_backfill_uses_mapped_period_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A 60-day window fetches period "3mo"; a dead symbol lands in failed_datasets."""
    from pipeline import run as run_mod

    calls: list[tuple[str, tuple]] = []

    class _FakeHistory:
        rows = [{"date": "2026-08-01", "close": 100.0}]

    class _FakeRegistry:
        def call(self, domain, op, cache_key, args=()):
            calls.append((cache_key, args))
            symbol, period = args
            if symbol == "IWM":
                raise RuntimeError("provider down")
            return {"result": _FakeHistory()}

    fake_universe = SimpleNamespace(us_equities=[SimpleNamespace(symbol="AAPL")])
    slices_written: list[list[dict]] = []
    reports: list[dict] = []

    def _fake_report(artifacts_dir, **kwargs):
        reports.append(kwargs)
        return artifacts_dir / "report.json"

    monkeypatch.setattr(run_mod, "build_registry", lambda settings: _FakeRegistry())
    monkeypatch.setattr(run_mod.AssetUniverse, "load", staticmethod(lambda settings: fake_universe))
    monkeypatch.setattr(
        run_mod,
        "StorageWriter",
        lambda data_dir: SimpleNamespace(write_slices=lambda name, rows: slices_written.append(rows)),
    )
    monkeypatch.setattr(run_mod, "write_run_report", _fake_report)

    assert run_mod.run_backfill(60) == 0
    periods = {args[1] for _, args in calls}
    assert periods == {"3mo"}  # 60 days maps to 3mo, not the old hardcoded 1y
    assert reports and reports[0]["failed_datasets"] == ["IWM"]
    # SPY benchmark series still written to history/market despite IWM failing.
    assert slices_written and slices_written[0][0]["symbol"] == "SPY"


# ---- shared row-count helper ----


def test_row_count_for_dict_and_object_agree() -> None:
    env = {"payload": {"assets": [1, 2, 3]}}
    assert row_count_for("equities", env["payload"]) == 3

    class _Obj:
        assets = [1, 2]

    assert row_count_for("equities", _Obj()) == 2

    # Derived datasets are single objects: not-applicable, never "empty" (#89).
    assert row_count_for("risk", {"anything": []}) is None
    assert row_count_for("nonexistent", {}) is None
    # A scalar payload under a counted spec is None, not 0 - the divergence #188 removed.
    assert row_count_for("equities", "not-a-mapping") is None


# ---- backfill_metadata hardening ----


def _minimal_envelope(status: str = "fresh", generated_at: str | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or "2026-08-21T12:00:00Z",
        "freshness_status": status,
        "provenance": {"provider": "test", "used_fallback": False, "from_cache": False},
        "payload": {},
    }


def _seed_valid_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    latest = data_dir / "latest"
    latest.mkdir(parents=True)
    for spec in registry.DATASETS:
        if spec.enveloped:
            (latest / spec.filenames[0]).write_text(json.dumps(_minimal_envelope()), encoding="utf-8")
    analysis_fixture = Path(__file__).parent.parent / "fixtures" / "analysis.zh-CN.json"
    valid_analysis = json.loads(analysis_fixture.read_text(encoding="utf-8"))
    for filename in registry.require("analysis").filenames:
        (latest / filename).write_text(json.dumps(valid_analysis), encoding="utf-8")
    for filename in registry.require("news_translations").filenames:
        (latest / filename).write_text(json.dumps({"items": []}), encoding="utf-8")
    return data_dir


def test_backfill_metadata_happy_path_writes_projection_pair(tmp_path: Path) -> None:
    data_dir = _seed_valid_data_dir(tmp_path)
    assert bfm.main(["--data-dir", str(data_dir)]) == 0
    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    sources = json.loads((data_dir / "metadata" / "sources.json").read_text(encoding="utf-8"))
    assert set(freshness["datasets"]) >= {"factlayer", "analysis", "news_translations"}
    assert freshness["datasets"]["analysis"]["status"] == "fresh"
    assert sources["domains"], "sources projection must carry provider domains"


def test_backfill_metadata_corrupt_file_skips_named_and_exits_one(tmp_path: Path) -> None:
    data_dir = _seed_valid_data_dir(tmp_path)
    equities_name = registry.require("equities").filenames[0]
    (data_dir / "latest" / equities_name).write_text("{corrupt json", encoding="utf-8")
    code = bfm.main(["--data-dir", str(data_dir)])
    assert code == 1
    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    # The projection renders the full vocabulary: a skipped dataset shows up as the
    # honest "missing", never as stale data pretending to be current.
    assert freshness["datasets"]["equities"]["status"] == "missing"
    assert freshness["datasets"]["sectors"]["status"] == "fresh"  # rest recorded (partial, flagged)


def test_backfill_metadata_invalid_ai_document_is_degraded_not_fresh(tmp_path: Path) -> None:
    data_dir = _seed_valid_data_dir(tmp_path)
    for filename in registry.require("analysis").filenames:
        (data_dir / "latest" / filename).write_text(json.dumps({"schema_version": "bogus"}), encoding="utf-8")
    assert bfm.main(["--data-dir", str(data_dir)]) == 0
    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    entry = freshness["datasets"]["analysis"]
    assert entry["status"] == "degraded"
    assert entry["reason"]["code"] == "provider_parse_error"


def test_backfill_metadata_missing_ai_document_is_missing(tmp_path: Path) -> None:
    data_dir = _seed_valid_data_dir(tmp_path)
    for filename in registry.require("news_translations").filenames:
        (data_dir / "latest" / filename).unlink()
    assert bfm.main(["--data-dir", str(data_dir)]) == 0
    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    entry = freshness["datasets"]["news_translations"]
    assert entry["status"] == "missing"
    assert entry["reason"]["code"] == "not_collected_this_run"


def test_frozen_now_guards_bad_timestamp() -> None:
    from pipeline.validation.freshness import expected_interval_minutes_for

    gen = "2026-08-21T12:00:00Z"
    frozen = bfm._frozen_now("macro", gen, "fresh")
    interval = expected_interval_minutes_for("macro", 480)
    expected = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=interval * 1.0)
    assert frozen == expected
    assert bfm._frozen_now("macro", gen, "degraded") is None  # clock ignored off the time ladder
    assert bfm._frozen_now("macro", "not-a-timestamp", "fresh") is None  # guarded, not crashing