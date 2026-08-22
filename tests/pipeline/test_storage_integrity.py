"""Storage integrity gates (#191): umask-derived publish modes, slice-consistency
validation, filesystem-driven history coverage, and single-sourced versions."""

from __future__ import annotations

import json
import os
from pathlib import Path


def test_write_json_honors_umask_derived_mode(tmp_path: Path) -> None:
    """Published files must be readable by others (Pages deploy), not mkstemp 0600."""
    from pipeline.storage.writer import StorageWriter

    writer = StorageWriter(tmp_path)
    target = writer.write_json(tmp_path / "probe.json", {"ok": True})
    umask = os.umask(0)
    os.umask(umask)
    expected = 0o644 & ~umask
    actual = target.stat().st_mode & 0o777
    assert actual == expected, f"mode {oct(actual)} != umask-derived {oct(expected)}"


def _write_consistent_series(root: Path, series: str, daily: list[dict]) -> None:
    sdir = root / "history" / series
    sdir.mkdir(parents=True)
    (sdir / "daily.json").write_text(json.dumps(daily), encoding="utf-8")
    (sdir / "30d.json").write_text(json.dumps(daily[-30:]), encoding="utf-8")
    (sdir / "90d.json").write_text(json.dumps(daily[-90:]), encoding="utf-8")
    (sdir / "index.json").write_text(json.dumps({"series": series, "count": len(daily)}), encoding="utf-8")


def test_check_slice_consistency_passes_on_consistent_tree(tmp_path: Path) -> None:
    """Consistent slices, including nested macro archives, produce no errors."""
    from pipeline.validation.ci_checks import CheckReport, check_slice_consistency

    daily = [{"date": f"2026-08-{d:02d}", "v": d} for d in range(1, 31)]
    for series in ("market", "macro/BAA10Y"):
        _write_consistent_series(tmp_path, series, daily)

    report = CheckReport()
    check_slice_consistency(tmp_path, report)
    assert not report.errors, report.issues


def test_check_slice_consistency_detects_diverged_slices_and_count(tmp_path: Path) -> None:
    """The #191 bug shape: write_slices writes four files non-atomically; a crash
    between them must now be DETECTED (stale 30d + wrong index count)."""
    from pipeline.validation.ci_checks import CheckReport, check_slice_consistency

    daily = [{"date": f"2026-08-{d:02d}", "v": d} for d in range(1, 31)]
    sdir = tmp_path / "history" / "market"
    sdir.mkdir(parents=True)
    (sdir / "daily.json").write_text(json.dumps(daily), encoding="utf-8")
    (sdir / "30d.json").write_text(json.dumps(daily[:10]), encoding="utf-8")
    (sdir / "index.json").write_text(json.dumps({"count": 5}), encoding="utf-8")

    report = CheckReport()
    check_slice_consistency(tmp_path, report)
    joined = chr(10).join(report.errors)
    assert "30d.json: diverged from daily.json tail" in joined
    assert "index.json: count 5 != 30 daily rows" in joined


def test_check_history_discovers_series_from_filesystem(tmp_path: Path) -> None:
    """Series coverage is glob-driven (#191): a non-literal archive dir gets checked."""
    from pipeline.validation.ci_checks import CheckReport, check_history

    rows = [{"date": "2026-08-01", "total_score": 50.0}]
    for series in ("risk", "market", "macro/BAA10Y"):
        sdir = tmp_path / "history" / series
        sdir.mkdir(parents=True)
        (sdir / "daily.json").write_text(json.dumps(rows), encoding="utf-8")

    report = CheckReport()
    check_history(tmp_path, report)
    assert not report.errors, report.issues
    # One daily per discovered series; missing 30d/90d are warn-only warm-up state.
    assert report.files_checked == 3


def test_translations_schema_version_single_source() -> None:
    """#191/T1 follow-up: record_translations restated the literal twice."""
    import pathlib as pl

    from pipeline.storage import writer as writer_mod

    assert writer_mod.TRANSLATIONS_SCHEMA_VERSION == "1.0.0"
    body = pl.Path(writer_mod.__file__).read_text(encoding="utf-8")
    q = chr(34)
    restated = [
        line
        for line in body.splitlines()
        if q + "1.0.0" + q in line and "TRANSLATIONS_SCHEMA_VERSION =" not in line
    ]
    assert restated == [], f"translations version literal restated: {restated}"
