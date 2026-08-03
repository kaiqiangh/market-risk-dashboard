"""Storage + validate_all + run.py CLI 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.settings import Settings
from pipeline.storage import StorageWriter
from pipeline.validation.validate_all import validate_all, validate_file

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


# ---------- StorageWriter ----------

def test_write_dataset_and_slices(tmp_path: Path) -> None:
    from pipeline.schemas import MacroDataset, MacroEnvelope

    writer = StorageWriter(tmp_path / "data")
    env = MacroEnvelope(
        generated_at="2026-08-03T10:00:00Z", schema_version="1.0.0", source="fred",
        source_updated_at="2026-08-03T10:00:00Z", freshness_status="fresh", data_quality=0.9,
        payload=MacroDataset(),
    )
    path = writer.write_dataset("macro", env)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["payload"] == {"rates": [], "credit": [], "inflation": [], "labor": [], "liquidity": [], "fx": [], "fedwatch": None}

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
    writer = StorageWriter(tmp_path / "data")
    writer.update_freshness("macro", "fresh", "ok")
    writer.write_sources_metadata({"quotes": [{"provider": "yfinance", "ok": True}]})
    writer.write_schema_version("1.0.0")
    assert (tmp_path / "data/metadata/freshness.json").exists()
    assert (tmp_path / "data/metadata/sources.json").exists()
    assert (tmp_path / "data/metadata/schema-version.json").exists()


# ---------- validate_all（复用 tests/fixtures） ----------

@pytest.mark.parametrize("name", ["macro.json", "equities.json", "sectors.json", "crypto.json", "news.json", "calendar.json", "risk.json", "facts.json", "analysis.zh-CN.json", "analysis.en.json"])
def test_validate_file_on_fixtures(name: str) -> None:
    assert validate_file(FIXTURES / name) == []


def test_validate_all_fixtures_pass() -> None:
    report = validate_all(FIXTURES, strict=False)
    assert report.ok
    assert report.files_checked == 10


def test_validate_all_strict_missing_fails(tmp_path: Path) -> None:
    report = validate_all(tmp_path, strict=True)
    assert not report.ok
    assert any("缺失" in issue for issue in report.issues)


# ---------- run.py CLI ----------

def test_run_dry_run_exits_zero() -> None:
    from pipeline.run import main

    assert main(["--dry-run"]) == 0
    assert main(["--full", "--dry-run"]) == 0
    assert main(["--market-only", "--dry-run"]) == 0
    assert main(["--news-only", "--dry-run", "--locale", "zh-CN"]) == 0
