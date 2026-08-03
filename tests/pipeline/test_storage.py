"""Storage + validate_all + run.py CLI 测试。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
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


def test_read_history_public_method(tmp_path: Path) -> None:
    """P2-9：writer.read_history 公开方法替代 run.py 私有 _read_json。"""
    writer = StorageWriter(tmp_path / "data")
    writer.write_slices("risk", [{"date": "2026-08-01", "total_score": 40.0}])
    writer.write_slices("risk", [{"date": "2026-08-02", "total_score": 42.0}])
    rows = writer.read_history("risk", "daily")
    assert len(rows) == 2
    assert rows[-1]["total_score"] == 42.0
    assert writer.read_history("risk", "30d")[-1]["date"] == "2026-08-02"
    assert writer.read_history("nonexistent", "daily") == []


def test_record_translations_metadata(tmp_path: Path) -> None:
    """P1-6：中译合并记录写入 metadata/translations.json。"""
    writer = StorageWriter(tmp_path / "data")
    writer.record_translations("merged", merged_items=3, reason="合并完成")
    data = json.loads((tmp_path / "data/metadata/translations.json").read_text(encoding="utf-8"))
    assert data["last_merge"]["status"] == "merged"
    assert data["last_merge"]["merged_items"] == 3
    assert data["last_merge"]["source_file"] == "news.zh-translations.json"
    writer.record_translations("missing", merged_items=0, reason="AI 未产出")
    data2 = json.loads((tmp_path / "data/metadata/translations.json").read_text(encoding="utf-8"))
    assert data2["last_merge"]["status"] == "missing"


def test_finalize_freshness_unified(tmp_path: Path) -> None:
    """P1-7：统一五态判定（degraded 优先于时间维度）。"""
    from pipeline.validation.freshness import finalize_freshness

    now = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
    fresh_ts = "2026-08-03T10:00:00Z"
    # 无数据 → missing
    assert finalize_freshness("macro", None, False, now=now) == "missing"
    # 时间新鲜 + 未降级 → fresh
    assert finalize_freshness("macro", fresh_ts, False, now=now) == "fresh"
    # 降级 → degraded（与时间无关）
    assert finalize_freshness("macro", fresh_ts, True, now=now) == "degraded"
    # 陈旧 → stale（macro 期望 240min；fresh_ts 距今 2h → fresh；更早 → delayed/stale）
    assert finalize_freshness("macro", "2026-08-03T04:00:00Z", False, now=now) == "delayed"
    assert finalize_freshness("macro", "2026-08-02T12:00:00Z", False, now=now) == "stale"


def test_frontend_freshness_sync() -> None:
    """P2-10：src/lib/freshness.ts 期望频率与 config/sources.yaml 保持同步。"""
    from pipeline.settings import PROJECT_ROOT, settings

    expectations = settings.load_sources().get("expectations", {})
    ts_source = (PROJECT_ROOT / "src" / "lib" / "freshness.ts").read_text(encoding="utf-8")
    assert expectations, "config/sources.yaml expectations 不应为空"
    for key, entry in expectations.items():
        minutes = int(entry.get("interval_minutes", 0))
        assert minutes > 0, f"sources.yaml {key} interval_minutes 非法"
        assert f"{key}: {minutes}" in ts_source, (
            f"src/lib/freshness.ts 缺少 {key}: {minutes}（与 config/sources.yaml 不同步）"
        )
    # 反向：前端 EXPECTED_INTERVALS_MIN 不应多出 sources.yaml 未登记的 key
    import re

    block = ts_source.split("export const EXPECTED_INTERVALS_MIN", 1)[1].split("};", 1)[0]
    frontend_keys = set(re.findall(r"^\s{2}(\w+): \d+", block, re.MULTILINE))
    expected_keys = set(expectations.keys())
    assert frontend_keys.issubset(expected_keys), f"前端多出未登记 key: {frontend_keys - expected_keys}"


# ---------- validate_all（复用 tests/fixtures） ----------

@pytest.mark.parametrize("name", ["macro.json", "equities.json", "sectors.json", "crypto.json", "news.json", "calendar.json", "risk.json", "dashboard.json", "facts.json", "analysis.zh-CN.json", "analysis.en.json"])
def test_validate_file_on_fixtures(name: str) -> None:
    assert validate_file(FIXTURES / name) == []


def test_validate_all_fixtures_pass() -> None:
    report = validate_all(FIXTURES, strict=False)
    assert report.ok
    assert report.files_checked == 11


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
