"""T05 data validator tests (pipeline/validation/ci_checks.py).

Covers: real data passes / duplicate news / NaN·Infinity / risk ranges / bilingual missing /
unknown language key / bilingual mismatch / stale warning / required file missing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.validation.ci_checks import (
    _reject_constant,
    load_json_strict,
    run_all,
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "public" / "data"
LATEST = DATA_DIR / "latest"


@pytest.fixture()
def now() -> datetime:
    return datetime.now(timezone.utc)


def test_real_data_passes(now: datetime) -> None:
    """Full public/data validation passes (0 ERROR; missing AI briefing allows WARNING)."""
    report = run_all(DATA_DIR, now=now)
    assert report.ok, f"real data validation failed: {report.errors}"
    assert report.files_checked >= 15


def test_duplicate_news_id_detected(tmp_path: Path, now: datetime) -> None:
    """Duplicate news id must be reported."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    # Copy real news.json then inject a duplicate id
    news = json.loads((LATEST / "news.json").read_text(encoding="utf-8"))
    item = news["payload"]["items"][0]
    news["payload"]["items"].append({**item, "id": item["id"]})
    (latest / "news.json").write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")

    # Other files missing → required-missing is also reported; only assert duplicate news is detected
    report = run_all(tmp_path, now=now)
    dup = [e for e in report.errors if "duplicate news" in e]
    assert dup, f"duplicate news not detected: {report.errors}"


def test_nan_infinity_rejected(tmp_path: Path, now: datetime) -> None:
    """NaN/Infinity constants must be rejected (Python json.loads accepts them by default)."""
    with pytest.raises(ValueError, match="illegal constant"):
        _reject_constant("NaN")
    with pytest.raises(ValueError, match="illegal constant"):
        _reject_constant("Infinity")

    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    (latest / "macro.json").write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="illegal constant"):
        load_json_strict(latest / "macro.json")


def test_risk_score_range_detected(tmp_path: Path, now: datetime) -> None:
    """Risk score out of [0,100] must be reported."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    risk = json.loads((LATEST / "risk.json").read_text(encoding="utf-8"))
    risk["payload"]["total_score"] = 150.0
    (latest / "risk.json").write_text(json.dumps(risk, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert any("total_score" in e and "150" in e for e in report.errors), report.errors


def test_analysis_pair_missing_one_side(tmp_path: Path, now: datetime) -> None:
    """analysis.zh-CN.json exists but en is missing → bilingual missing error."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    # Generate a minimal valid analysis file (only to trigger the pair check)
    analysis = json.loads((Path(__file__).parent.parent / "fixtures" / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    (latest / "analysis.zh-CN.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert any("missing bilingual analysis file" in e for e in report.errors), report.errors


def test_unknown_language_key_detected(tmp_path: Path, now: datetime) -> None:
    """Unknown language analysis.fr.json → error."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    (latest / "analysis.fr.json").write_text("{}", encoding="utf-8")
    report = run_all(tmp_path, now=now)
    assert any("unknown language key" in e for e in report.errors), report.errors


def test_bilingual_inconsistency_detected(tmp_path: Path, now: datetime) -> None:
    """Bilingual market_state mismatch → error."""
    fixtures = Path(__file__).parent.parent / "fixtures"
    zh = json.loads((fixtures / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    en = json.loads((fixtures / "analysis.en.json").read_text(encoding="utf-8"))
    en["market_state"] = "different_value"
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    (latest / "analysis.zh-CN.json").write_text(json.dumps(zh, ensure_ascii=False), encoding="utf-8")
    (latest / "analysis.en.json").write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")
    (latest / "facts.json").write_text((LATEST / "facts.json").read_text(encoding="utf-8"), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert any("AI bilingual conclusion mismatch" in e and "market_state" in e for e in report.errors), report.errors


def test_stale_is_warning_not_error(tmp_path: Path, now: datetime) -> None:
    """Stale data → WARNING (does not block publishing)."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    macro = json.loads((LATEST / "macro.json").read_text(encoding="utf-8"))
    macro["generated_at"] = "2020-01-01T00:00:00Z"
    (latest / "macro.json").write_text(json.dumps(macro, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert not any("is stale" in e for e in report.errors)
    assert any("is stale" in w for w in report.warnings), report.warnings


def test_required_file_missing(tmp_path: Path, now: datetime) -> None:
    """Required dataset missing → error."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    report = run_all(tmp_path, now=now)
    assert any("file missing (required dataset)" in e for e in report.errors), report.errors
