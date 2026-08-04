"""Storage + validate_all + run.py CLI tests."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.settings import Settings
from pipeline.storage import StorageWriter
from pipeline.validation.validate_all import validate_all, validate_file


# ---------- StorageWriter ----------

def test_write_dataset_and_slices(tmp_path: Path) -> None:
    from pipeline.schemas import MacroEnvelope
    from pipeline.schemas.envelope import SCHEMA_VERSION
    from tests.pipeline.factories import make_envelope

    writer = StorageWriter(tmp_path / "data")
    env = MacroEnvelope.model_validate(make_envelope("macro"))
    assert env.schema_version == SCHEMA_VERSION
    path = writer.write_dataset("macro", env)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["payload"]["rates"][0]["key"] == "dgs10"

    daily = [{"date": f"2026-07-{i:02d}", "total_score": i} for i in range(1, 100)]
    writer.write_slices("risk", daily)
    assert len(json.loads((tmp_path / "data/history/risk/daily.json").read_text())) == 99
    assert len(json.loads((tmp_path / "data/history/risk/30d.json").read_text())) == 30
    assert len(json.loads((tmp_path / "data/history/risk/90d.json").read_text())) == 90


def test_history_dedupe_by_date(tmp_path: Path) -> None:
    writer = StorageWriter(tmp_path / "data")
    writer.write_slices("risk", [{"date": "2026-08-03", "total_score": 50.0}])
    writer.write_slices("risk", [{"date": "2026-08-03", "total_score": 55.0}])
    daily = json.loads((tmp_path / "data/history/risk/daily.json").read_text())
    assert len(daily) == 1
    assert daily[0]["total_score"] == 55.0


def test_metadata_writes(tmp_path: Path) -> None:
    from pipeline.schemas.envelope import SCHEMA_VERSION

    writer = StorageWriter(tmp_path / "data")
    writer.update_freshness("macro", "fresh", "ok")
    writer.write_sources_metadata({"quotes": [{"provider": "yfinance", "ok": True}]})
    writer.write_schema_version(SCHEMA_VERSION)
    assert (tmp_path / "data/metadata/freshness.json").exists()
    assert (tmp_path / "data/metadata/sources.json").exists()
    assert (tmp_path / "data/metadata/schema-version.json").exists()


def test_read_history_public_method(tmp_path: Path) -> None:
    """P2-9: writer.read_history public method replaces run.py's private _read_json."""
    writer = StorageWriter(tmp_path / "data")
    writer.write_slices("risk", [{"date": "2026-08-01", "total_score": 40.0}])
    writer.write_slices("risk", [{"date": "2026-08-02", "total_score": 42.0}])
    rows = writer.read_history("risk", "daily")
    assert len(rows) == 2
    assert rows[-1]["total_score"] == 42.0
    assert writer.read_history("risk", "30d")[-1]["date"] == "2026-08-02"
    assert writer.read_history("nonexistent", "daily") == []


def test_record_translations_metadata(tmp_path: Path) -> None:
    """P1-6: Chinese translation merge record written to metadata/translations.json."""
    writer = StorageWriter(tmp_path / "data")
    writer.record_translations("merged", merged_items=3, reason="merge completed")
    data = json.loads((tmp_path / "data/metadata/translations.json").read_text(encoding="utf-8"))
    assert data["last_merge"]["status"] == "merged"
    assert data["last_merge"]["merged_items"] == 3
    assert data["last_merge"]["source_file"] == "news.zh-translations.json"
    writer.record_translations("missing", merged_items=0, reason="AI not produced")
    data2 = json.loads((tmp_path / "data/metadata/translations.json").read_text(encoding="utf-8"))
    assert data2["last_merge"]["status"] == "missing"


def test_finalize_freshness_unified(tmp_path: Path) -> None:
    """P1-7: unified five-state determination (degraded takes priority over the time dimension)."""
    from pipeline.validation.freshness import finalize_freshness

    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    fresh_ts = "2026-08-03T10:00:00Z"
    # no data → missing
    assert finalize_freshness("macro", None, False, now=now) == "missing"
    # time fresh + not degraded → fresh
    assert finalize_freshness("macro", fresh_ts, False, now=now) == "fresh"
    # degraded → degraded (independent of time)
    assert finalize_freshness("macro", fresh_ts, True, now=now) == "degraded"
    # stale → stale (macro expected 240min; fresh_ts is 2h ago → fresh; earlier → delayed/stale)
    assert finalize_freshness("macro", "2026-08-03T04:00:00Z", False, now=now) == "delayed"
    assert finalize_freshness("macro", "2026-08-02T12:00:00Z", False, now=now) == "stale"


def test_frontend_freshness_sync() -> None:
    """P2-10: src/lib/freshness.ts expected frequencies stay in sync with config/sources.yaml."""
    from pipeline.settings import PROJECT_ROOT, settings

    expectations = settings.load_sources().get("expectations", {})
    ts_source = (PROJECT_ROOT / "src" / "lib" / "freshness.ts").read_text(encoding="utf-8")
    assert expectations, "config/sources.yaml expectations must not be empty"
    for key, entry in expectations.items():
        minutes = int(entry.get("interval_minutes", 0))
        assert minutes > 0, f"sources.yaml {key} interval_minutes invalid"
        assert f"{key}: {minutes}" in ts_source, (
            f"src/lib/freshness.ts missing {key}: {minutes} (out of sync with config/sources.yaml)"
        )
    # Reverse: frontend EXPECTED_INTERVALS_MIN must not contain keys unregistered in sources.yaml
    import re

    block = ts_source.split("export const EXPECTED_INTERVALS_MIN", 1)[1].split("};", 1)[0]
    frontend_keys = set(re.findall(r"^\s{2}(\w+): \d+", block, re.MULTILINE))
    expected_keys = set(expectations.keys())
    assert frontend_keys.issubset(expected_keys), f"frontend has unregistered keys: {frontend_keys - expected_keys}"


# ---------- validate_all (generated documents since #73) ----------
# Generated documents carry DEFAULT_NOW timestamps; the real clock ages them, so freshness
# annotation is exempted exactly as it was for the deleted static fixtures: these tests verify
# schema/format (T02 intent); staleness is evaluated on live data, not generated documents.

def _write_generated_latest(tmp_path: Path) -> Path:
    """Write the 11 known documents (factory-generated) to a tmp latest/ dir."""
    from tests.pipeline.factories import default_latest_files

    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    for filename, content in default_latest_files().items():
        (latest / filename).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return latest


def _issues_without_freshness(path: Path) -> list[str]:
    return [i for i in validate_file(path) if "stale" not in i]


@pytest.mark.parametrize("name", ["macro.json", "equities.json", "sectors.json", "crypto.json", "news.json", "calendar.json", "risk.json", "dashboard.json", "facts.json", "analysis.zh-CN.json", "analysis.en.json"])
def test_validate_file_on_generated_documents(tmp_path: Path, name: str) -> None:
    assert _issues_without_freshness(_write_generated_latest(tmp_path) / name) == []


def test_validate_all_generated_documents_pass(tmp_path: Path) -> None:
    latest = _write_generated_latest(tmp_path)
    report = validate_all(latest, strict=False)
    issues = [i for i in report.issues if "stale" not in i]
    assert not issues
    assert report.files_checked == 11


def test_validate_all_strict_missing_fails(tmp_path: Path) -> None:
    report = validate_all(tmp_path, strict=True)
    assert not report.ok
    assert any("missing" in issue for issue in report.issues)


# ---------- run.py CLI ----------

def test_run_dry_run_exits_zero() -> None:
    from pipeline.run import main

    assert main(["--dry-run"]) == 0
    assert main(["--full", "--dry-run"]) == 0
    assert main(["--market-only", "--dry-run"]) == 0
    assert main(["--news-only", "--dry-run", "--locale", "zh-CN"]) == 0


# ---------- #63: an unattended run writes good data or says loudly that it did not ----------


# ---- Defect 1: writes are atomic ----

def test_write_json_is_atomic_on_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process killed between the temp write and the replace leaves the prior file intact.

    The failure is injected at `os.replace`, which is the last operation and the only one
    that can be interrupted after the temp file holds complete data. Before #63 the write
    went straight to the target via `write_text`, so an interrupt truncated it in place.
    """
    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    writer.write_json(target, {"generation": "first", "rows": [1, 2, 3]})
    original = target.read_text(encoding="utf-8")

    def _die(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr("pipeline.storage.writer.os.replace", _die)
    with pytest.raises(KeyboardInterrupt):
        writer.write_json(target, {"generation": "second", "rows": [4, 5, 6]})

    # The reader still sees the complete previous version, byte for byte.
    assert target.read_text(encoding="utf-8") == original
    assert json.loads(target.read_text(encoding="utf-8"))["generation"] == "first"


def test_write_json_leaves_no_temp_file_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An interrupted write cleans up its own temp file rather than littering latest/."""
    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    writer.write_json(target, {"generation": "first"})

    def _die(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt("killed mid-write")

    monkeypatch.setattr("pipeline.storage.writer.os.replace", _die)
    with pytest.raises(KeyboardInterrupt):
        writer.write_json(target, {"generation": "second"})

    assert sorted(p.name for p in target.parent.iterdir()) == ["macro.json"]


def test_write_json_temp_file_shares_target_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The temp file must sit beside the target, or os.replace can cross a filesystem and stop being atomic."""
    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    seen: list[Path] = []

    real_replace = os.replace

    def _record(src: str | Path, dst: str | Path) -> None:
        seen.append(Path(src))
        real_replace(src, dst)

    monkeypatch.setattr("pipeline.storage.writer.os.replace", _record)
    writer.write_json(target, {"ok": True})

    assert seen, "write_json must go through os.replace"
    assert seen[0].parent == target.parent, f"temp file {seen[0]} is not in the target directory"


def test_write_json_fsyncs_before_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """fsync is part of the atomic-write guarantee (#63): the payload must be durable
    before `os.replace` makes it visible, or a crash can surface a zero-length file.

    The ticket lists "temp-file + fsync + os.replace"; the first and third are pinned
    above, this pins the middle one.
    """
    import pipeline.storage.writer as writer_mod

    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    events: list[str] = []
    real_replace = os.replace

    def _record_fsync(fd: int) -> None:
        events.append(f"fsync:{fd}")

    def _record_replace(src: str | Path, dst: str | Path) -> None:
        events.append(f"replace:{Path(src).name}")
        real_replace(src, dst)

    monkeypatch.setattr(writer_mod.os, "fsync", _record_fsync)
    monkeypatch.setattr(writer_mod.os, "replace", _record_replace)
    writer.write_json(target, {"ok": True})

    assert len(events) == 2, f"write_json must fsync then replace, saw: {events}"
    assert events[0].startswith("fsync:"), f"fsync must precede replace, saw: {events}"
    assert events[1].startswith("replace:"), f"replace must follow fsync, saw: {events}"


def test_write_json_still_writes_readable_output(tmp_path: Path) -> None:
    """Atomicity must not change what lands on disk."""
    from pipeline.schemas.envelope import SCHEMA_VERSION

    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    payload = {"schema_version": SCHEMA_VERSION, "values": [1, 2, 3], "nested": {"zh": "中文"}}

    writer.write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_write_json_overwrites_existing_file(tmp_path: Path) -> None:
    """os.replace onto an existing target succeeds (it must not require an absent destination)."""
    writer = StorageWriter(tmp_path / "data")
    target = tmp_path / "data" / "latest" / "macro.json"
    writer.write_json(target, {"generation": "first"})
    writer.write_json(target, {"generation": "second"})

    assert json.loads(target.read_text(encoding="utf-8"))["generation"] == "second"


# ---- Defect 2: corruption is named, not swallowed ----

def test_corrupt_existing_file_raises(tmp_path: Path) -> None:
    """A corrupt JSON file raises a named error identifying the path.

    Before #63 `_read_json` returned the default `[]`, so `write_slices` treated months of
    history as empty and the next write replaced it with a single row.
    """
    from pipeline.storage.writer import CorruptDataError

    writer = StorageWriter(tmp_path / "data")
    corrupt = tmp_path / "data" / "history" / "risk" / "daily.json"
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_text('[{"date": "2026-08-01", "total_sc', encoding="utf-8")

    with pytest.raises(CorruptDataError) as excinfo:
        writer.read_history("risk", "daily")

    message = str(excinfo.value)
    assert "daily.json" in message, f"the error must identify the path, got: {message}"
    assert excinfo.value.path == corrupt


def test_corrupt_history_is_not_silently_emptied(tmp_path: Path) -> None:
    """The data-loss scenario end to end: a corrupt history file is never overwritten."""
    from pipeline.storage.writer import CorruptDataError

    writer = StorageWriter(tmp_path / "data")
    daily = tmp_path / "data" / "history" / "risk" / "daily.json"
    daily.parent.mkdir(parents=True, exist_ok=True)
    corrupt_bytes = '[{"date": "2026-07-01", "total_score": 40}, {"date": "2026-07-02", '
    daily.write_text(corrupt_bytes, encoding="utf-8")

    with pytest.raises(CorruptDataError):
        writer.write_slices("risk", [{"date": "2026-08-04", "total_score": 62.5}])

    # Untouched — a human can still salvage it.
    assert daily.read_text(encoding="utf-8") == corrupt_bytes


def test_corrupt_error_is_raised_for_every_reader(tmp_path: Path) -> None:
    """Every public read path surfaces corruption; none of them falls back to a default."""
    from pipeline.storage.writer import CorruptDataError

    writer = StorageWriter(tmp_path / "data")
    (tmp_path / "data" / "latest" / "macro.json").write_text("{oops", encoding="utf-8")
    (tmp_path / "data" / "metadata" / "freshness.json").write_text("{oops", encoding="utf-8")

    with pytest.raises(CorruptDataError):
        writer.read_latest("macro")
    with pytest.raises(CorruptDataError):
        writer.update_freshness("macro", "fresh", "ok")


def test_missing_file_still_returns_default(tmp_path: Path) -> None:
    """Absent is not corrupt. A first run must still start from the default."""
    writer = StorageWriter(tmp_path / "data")

    assert writer.read_history("risk", "daily") == []
    assert writer.read_latest("macro") is None


def test_empty_file_is_treated_as_corrupt(tmp_path: Path) -> None:
    """A zero-length file is the signature of an interrupted pre-#63 write — not an empty list."""
    from pipeline.storage.writer import CorruptDataError

    writer = StorageWriter(tmp_path / "data")
    daily = tmp_path / "data" / "history" / "risk" / "daily.json"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text("", encoding="utf-8")

    with pytest.raises(CorruptDataError) as excinfo:
        writer.read_history("risk", "daily")

    # The distinct reason names the failure mode — an interrupted write — rather than
    # letting the empty file read as a JSONDecodeError on "".
    assert "is empty (the signature of an interrupted write)" in str(excinfo.value)


# ---- Defect 3: undated history rows are rejected ----

def test_undated_history_row_rejected(tmp_path: Path) -> None:
    """A row with no date raises a named error at write time."""
    from pipeline.storage.writer import UndatedRowError

    writer = StorageWriter(tmp_path / "data")

    with pytest.raises(UndatedRowError):
        writer.write_slices("risk", [{"total_score": 62.5}])


def test_two_undated_rows_cannot_collapse(tmp_path: Path) -> None:
    """The data-loss shape: before #63 both rows keyed to "" and the second erased the first."""
    from pipeline.storage.writer import UndatedRowError

    writer = StorageWriter(tmp_path / "data")
    rows = [{"total_score": 40.0}, {"total_score": 55.0}]

    with pytest.raises(UndatedRowError):
        writer.write_slices("risk", rows)

    assert not (tmp_path / "data" / "history" / "risk" / "daily.json").exists()


@pytest.mark.parametrize("bad_date", ["", None])
def test_blank_and_null_dates_rejected(tmp_path: Path, bad_date: object) -> None:
    """Blank and null are the two ways a row reached the "" key."""
    from pipeline.storage.writer import UndatedRowError

    writer = StorageWriter(tmp_path / "data")

    with pytest.raises(UndatedRowError):
        writer.write_slices("risk", [{"date": bad_date, "total_score": 1.0}])


def test_undated_row_rejected_on_append(tmp_path: Path) -> None:
    """append_history shares the merge path and must reject undated rows too."""
    from pipeline.storage.writer import UndatedRowError

    writer = StorageWriter(tmp_path / "data")
    writer.append_history("risk", {"date": "2026-08-01", "total_score": 40.0})

    with pytest.raises(UndatedRowError):
        writer.append_history("risk", {"total_score": 55.0})

    # The good row survived the rejected one.
    assert writer.read_history("risk", "daily") == [{"date": "2026-08-01", "total_score": 40.0}]


def test_undated_row_in_existing_history_is_named(tmp_path: Path) -> None:
    """Undated rows already on disk are reported, not silently merged onto one another."""
    from pipeline.storage.writer import UndatedRowError

    writer = StorageWriter(tmp_path / "data")
    daily = tmp_path / "data" / "history" / "risk" / "daily.json"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(json.dumps([{"total_score": 1.0}, {"total_score": 2.0}]), encoding="utf-8")

    with pytest.raises(UndatedRowError):
        writer.write_slices("risk", [{"date": "2026-08-04", "total_score": 62.5}])


def test_dated_rows_still_merge_and_dedupe(tmp_path: Path) -> None:
    """Rejecting undated rows must not disturb the normal dedupe-by-date path."""
    writer = StorageWriter(tmp_path / "data")
    writer.write_slices("risk", [{"date": "2026-08-01", "total_score": 40.0}])
    writer.write_slices("risk", [{"date": "2026-08-01", "total_score": 45.0}, {"date": "2026-08-02", "total_score": 50.0}])

    rows = writer.read_history("risk", "daily")
    assert [r["date"] for r in rows] == ["2026-08-01", "2026-08-02"]
    assert rows[0]["total_score"] == 45.0


# ---- Defect 4: the run report distinguishes a clean run from a partial one ----

def test_run_report_lists_failed_datasets(tmp_path: Path) -> None:
    """A run with one failing dataset produces a report naming it."""
    from pipeline.report import write_run_report

    path = write_run_report(
        tmp_path / "artifacts",
        command="full",
        ok=True,
        durations={"total": 12.5},
        provider_status={},
        degraded=["crypto: coingecko rate limited"],
        dataset_counts={"latest": 8},
        failed_datasets=["sectors"],
        skipped_datasets=["calendar"],
        degraded_datasets=["crypto"],
    )
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["failed_datasets"] == ["sectors"]
    assert report["skipped_datasets"] == ["calendar"]
    assert report["degraded_datasets"] == ["crypto"]
    assert report["clean"] is False, "a run with a failed dataset is not clean"


def test_run_report_marks_a_clean_run_clean(tmp_path: Path) -> None:
    """A run with nothing failed, degraded or skipped is distinguishable at a glance."""
    from pipeline.report import write_run_report

    path = write_run_report(
        tmp_path / "artifacts",
        command="full",
        ok=True,
        durations={"total": 10.0},
        provider_status={},
        degraded=[],
        dataset_counts={"latest": 8},
    )
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["clean"] is True
    assert report["failed_datasets"] == []
    assert report["degraded_datasets"] == []
    assert report["skipped_datasets"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("failed_datasets", ["macro"]),
        ("degraded_datasets", ["macro"]),
        ("skipped_datasets", ["macro"]),
    ],
)
def test_any_imperfect_dataset_makes_the_run_unclean(tmp_path: Path, field: str, value: list[str]) -> None:
    """Failed, degraded and skipped each independently disqualify a run from "clean"."""
    from pipeline.report import write_run_report

    path = write_run_report(
        tmp_path / "artifacts",
        command="full",
        ok=True,
        durations={},
        provider_status={},
        degraded=[],
        dataset_counts={},
        **{field: value},
    )

    assert json.loads(path.read_text(encoding="utf-8"))["clean"] is False


def test_run_report_marks_a_failed_run_unclean(tmp_path: Path) -> None:
    """ok=False is never clean, whatever the dataset lists say."""
    from pipeline.report import write_run_report

    path = write_run_report(
        tmp_path / "artifacts",
        command="full",
        ok=False,
        durations={},
        provider_status={},
        degraded=[],
        dataset_counts={},
        error="risk computation failed",
    )
    report = json.loads(path.read_text(encoding="utf-8"))

    assert report["clean"] is False
    assert report["error"] == "risk computation failed"


def test_free_text_degraded_note_makes_the_run_unclean(tmp_path: Path) -> None:
    """A provider note without a matching dataset entry still means something went wrong."""
    from pipeline.report import write_run_report

    path = write_run_report(
        tmp_path / "artifacts",
        command="full",
        ok=True,
        durations={},
        provider_status={},
        degraded=["crypto: coingecko rate limited"],
        dataset_counts={},
    )

    assert json.loads(path.read_text(encoding="utf-8"))["clean"] is False


# ---- Defect 4: the lists the run report is fed are derived, not hand-maintained ----

#: The instant the seeded freshness entries were "written" and, for the existing tests,
#: the run-start passed to `dataset_health` — so the entries count as written during the
#: run. Newer tests vary this to pin the stale-entry rule (#63 amendment, QA finding 1).
_RUN_START = "2026-08-04T00:00:00Z"


def _write_freshness(data_dir: Path, statuses: dict[str, str], *, updated_at: str = _RUN_START) -> None:
    """Seed metadata/freshness.json the way a run would leave it."""
    from pipeline.schemas.envelope import SCHEMA_VERSION

    path = data_dir / "metadata" / "freshness.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "datasets": {
                    name: {"status": status, "reason": "", "updated_at": updated_at}
                    for name, status in statuses.items()
                },
            }
        ),
        encoding="utf-8",
    )


def test_dataset_health_names_missing_and_degraded_datasets(tmp_path: Path) -> None:
    """A full run with one missing and one degraded dataset names both."""
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    data_dir = tmp_path / "data"
    statuses = {name: "fresh" for name in FULL_RUN_DATASETS}
    statuses["sectors"] = "missing"
    statuses["crypto"] = "degraded"
    _write_freshness(data_dir, statuses)

    health = dataset_health(StorageWriter(data_dir), "full", run_started_at=_RUN_START)

    assert health["failed"] == ["sectors"]
    assert health["degraded"] == ["crypto"]
    assert health["skipped"] == []


def test_dataset_health_reports_a_clean_full_run_as_clean(tmp_path: Path) -> None:
    """Everything fresh means nothing to report — the three lists are empty."""
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    data_dir = tmp_path / "data"
    _write_freshness(data_dir, {name: "fresh" for name in FULL_RUN_DATASETS})

    assert dataset_health(StorageWriter(data_dir), "full", run_started_at=_RUN_START) == {
        "failed": [],
        "degraded": [],
        "skipped": [],
    }


def test_dataset_health_counts_stale_as_degraded_but_not_delayed(tmp_path: Path) -> None:
    """`stale` is a problem; `delayed` is the ordinary state of a slow-cadence dataset.

    Counting `delayed` would make `clean` false on nearly every run and the field would
    stop carrying information.
    """
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    data_dir = tmp_path / "data"
    statuses = {name: "fresh" for name in FULL_RUN_DATASETS}
    statuses["macro"] = "stale"
    statuses["calendar"] = "delayed"
    _write_freshness(data_dir, statuses)

    health = dataset_health(StorageWriter(data_dir), "full", run_started_at=_RUN_START)

    assert health["degraded"] == ["macro"]
    assert "calendar" not in health["degraded"]
    assert "calendar" not in health["failed"]


def test_dataset_health_reports_datasets_a_partial_command_skipped(tmp_path: Path) -> None:
    """`--market-only` leaves most of the dashboard on yesterday's data and must say so."""
    from pipeline.run import dataset_health

    data_dir = tmp_path / "data"
    _write_freshness(data_dir, {"equities": "fresh", "sectors": "fresh", "crypto": "fresh"})

    health = dataset_health(StorageWriter(data_dir), "market-only", run_started_at=_RUN_START)

    assert health["failed"] == []
    assert health["degraded"] == []
    assert health["skipped"] == ["macro", "news", "calendar", "risk", "facts", "dashboard"]


def test_dataset_health_treats_an_unrecorded_attempt_as_failed(tmp_path: Path) -> None:
    """A dataset the command attempted but never recorded did not finish writing."""
    from pipeline.run import dataset_health

    data_dir = tmp_path / "data"
    _write_freshness(data_dir, {"equities": "fresh", "crypto": "fresh"})

    health = dataset_health(StorageWriter(data_dir), "market-only", run_started_at=_RUN_START)

    assert health["failed"] == ["sectors"]


def test_dataset_health_treats_a_stale_fresh_entry_from_a_previous_run_as_failed(tmp_path: Path) -> None:
    """A `fresh` entry written by a previous run must not mask a dataset that died early.

    QA finding 1: `dataset_health` used to classify a dataset as failed only when its
    entry was absent or `missing`. A STALE `fresh` entry from yesterday therefore made a
    dataset that crashed before this run's freshness write invisible — `{failed: [],
    degraded: [], skipped: []}` and `clean: true`. The run knows when it started; an
    entry whose `updated_at` predates the run start is a previous run's record, and the
    dataset counts as failed regardless of the status it carries.
    """
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    data_dir = tmp_path / "data"
    _write_freshness(data_dir, {name: "fresh" for name in FULL_RUN_DATASETS}, updated_at="2026-08-03T00:00:00Z")

    health = dataset_health(StorageWriter(data_dir), "full", run_started_at="2026-08-05T00:00:00Z")

    assert health["failed"] == list(FULL_RUN_DATASETS), (
        "yesterday's fresh entries must not hide datasets that never wrote this run"
    )
    assert health["degraded"] == []


def test_dataset_health_accepts_entries_written_during_this_run(tmp_path: Path) -> None:
    """Freshness records updated after the run started are evidence the dataset survived."""
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    data_dir = tmp_path / "data"
    _write_freshness(data_dir, {name: "fresh" for name in FULL_RUN_DATASETS}, updated_at="2026-08-05T00:00:00Z")

    assert dataset_health(StorageWriter(data_dir), "full", run_started_at="2026-08-05T00:00:00Z") == {
        "failed": [],
        "degraded": [],
        "skipped": [],
    }


def test_dataset_health_before_the_first_run_fails_everything(tmp_path: Path) -> None:
    """No freshness metadata at all is not a clean run."""
    from pipeline.run import FULL_RUN_DATASETS, dataset_health

    health = dataset_health(StorageWriter(tmp_path / "data"), "full", run_started_at=_RUN_START)

    assert health["failed"] == list(FULL_RUN_DATASETS)


def test_partial_command_writes_a_run_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--market-only` must write a run report naming skipped and degraded datasets.

    QA finding 2: the single-domain branches of main() returned 0 without calling
    `dataset_health` or `write_run_report`, so a degraded `--market-only` run produced
    zero run reports — the skipped-dataset machinery was dead code in the real flow.
    """
    import pipeline.run as run_mod
    from pipeline.schemas import (
        CryptoDataset,
        CryptoEnvelope,
        EquitiesDataset,
        EquitiesEnvelope,
        SectorsDataset,
        SectorsEnvelope,
    )
    from pipeline.schemas.envelope import SCHEMA_VERSION

    data_dir = tmp_path / "data"
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(
        run_mod,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=artifacts_dir),
    )

    def _fake_collection(command: str) -> dict:
        return {
            "durations": {"market": 1.0, "collection": 1.0},
            "degraded": ["crypto: coingecko rate limited"],
            "provider_status": {"quotes": [{"provider": "yfinance", "ok": True}]},
            "histories": {},
            "qualities": [0.8, 0.8, 0.8],
            "macro_meta": {},
            "equities": EquitiesEnvelope(
                generated_at="2026-08-05T00:00:00Z", schema_version=SCHEMA_VERSION, source="yfinance",
                source_updated_at="2026-08-05T00:00:00Z", freshness_status="fresh",
                data_quality=0.9, payload=EquitiesDataset(),
            ),
            "crypto": CryptoEnvelope(
                generated_at="2026-08-05T00:00:00Z", schema_version=SCHEMA_VERSION, source="coingecko",
                source_updated_at="2026-08-05T00:00:00Z", freshness_status="fresh",
                data_quality=0.9, payload=CryptoDataset(),
            ),
            "sectors": SectorsEnvelope(
                generated_at="2026-08-05T00:00:00Z", schema_version=SCHEMA_VERSION, source="yfinance",
                source_updated_at="2026-08-05T00:00:00Z", freshness_status="fresh",
                data_quality=0.9, payload=SectorsDataset(),
            ),
        }

    monkeypatch.setattr(run_mod, "_run_collection", _fake_collection)

    assert run_mod.main(["--market-only"]) == 0

    reports = sorted((artifacts_dir / "logs").glob("run-report-*.json"))
    assert len(reports) == 1, f"a partial run must write exactly one run report, found {len(reports)}"
    report = json.loads(reports[0].read_text(encoding="utf-8"))

    assert report["command"] == "market-only"
    assert report["clean"] is False, "a degraded partial run is not clean"
    assert report["failed_datasets"] == []
    assert "macro" in report["skipped_datasets"] and "news" in report["skipped_datasets"]
    assert report["degraded"] == ["crypto: coingecko rate limited"]
    assert set(report["degraded_datasets"]) == {"equities", "crypto", "sectors"}


def test_dataset_health_surfaces_corrupt_freshness_metadata(tmp_path: Path) -> None:
    """Corrupt metadata must not be read as "no problems found" (#63 defect 2)."""
    from pipeline.run import dataset_health
    from pipeline.storage.writer import CorruptDataError

    data_dir = tmp_path / "data"
    writer = StorageWriter(data_dir)
    (data_dir / "metadata" / "freshness.json").write_text("{oops", encoding="utf-8")

    with pytest.raises(CorruptDataError):
        dataset_health(writer, "full", run_started_at=_RUN_START)
