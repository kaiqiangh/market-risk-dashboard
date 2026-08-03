"""T05 数据校验器测试（pipeline/validation/ci_checks.py）。

覆盖：真实数据通过 / 重复新闻 / NaN·Infinity / 风险范围 / 中英文缺失 /
未知语言 key / 双语不一致 / 过期告警 / 必填文件缺失。
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
    """真实 public/data 全量校验通过（0 ERROR；AI 简报未生成允许 WARNING）。"""
    report = run_all(DATA_DIR, now=now)
    assert report.ok, f"真实数据校验失败: {report.errors}"
    assert report.files_checked >= 15


def test_duplicate_news_id_detected(tmp_path: Path, now: datetime) -> None:
    """重复新闻 id 必须报错。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    # 复制真实 news.json 后注入重复 id
    news = json.loads((LATEST / "news.json").read_text(encoding="utf-8"))
    item = news["payload"]["items"][0]
    news["payload"]["items"].append({**item, "id": item["id"]})
    (latest / "news.json").write_text(json.dumps(news, ensure_ascii=False), encoding="utf-8")

    # 缺其他文件 → 也会报必填缺失；只断言重复新闻被检出
    report = run_all(tmp_path, now=now)
    dup = [e for e in report.errors if "重复新闻" in e]
    assert dup, f"未检出重复新闻: {report.errors}"


def test_nan_infinity_rejected(tmp_path: Path, now: datetime) -> None:
    """NaN/Infinity 常量必须被拒绝（Python json.loads 默认接受）。"""
    with pytest.raises(ValueError, match="非法常量"):
        _reject_constant("NaN")
    with pytest.raises(ValueError, match="非法常量"):
        _reject_constant("Infinity")

    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    (latest / "macro.json").write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="非法常量"):
        load_json_strict(latest / "macro.json")


def test_risk_score_range_detected(tmp_path: Path, now: datetime) -> None:
    """风险分数超出 [0,100] 必须报错。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    risk = json.loads((LATEST / "risk.json").read_text(encoding="utf-8"))
    risk["payload"]["total_score"] = 150.0
    (latest / "risk.json").write_text(json.dumps(risk, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert any("total_score" in e and "150" in e for e in report.errors), report.errors


def test_analysis_pair_missing_one_side(tmp_path: Path, now: datetime) -> None:
    """analysis.zh-CN.json 存在而 en 缺失 → 中英文缺失报错。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    # 生成一个最小合法分析文件（仅用于触发成对检查）
    analysis = json.loads((Path(__file__).parent.parent / "fixtures" / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    (latest / "analysis.zh-CN.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert any("中英文分析文件缺失" in e for e in report.errors), report.errors


def test_unknown_language_key_detected(tmp_path: Path, now: datetime) -> None:
    """未知语言 analysis.fr.json → 报错。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    (latest / "analysis.fr.json").write_text("{}", encoding="utf-8")
    report = run_all(tmp_path, now=now)
    assert any("未知语言 key" in e for e in report.errors), report.errors


def test_bilingual_inconsistency_detected(tmp_path: Path, now: datetime) -> None:
    """双语 market_state 不一致 → 报错。"""
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
    assert any("AI 双语结论不一致" in e and "market_state" in e for e in report.errors), report.errors


def test_stale_is_warning_not_error(tmp_path: Path, now: datetime) -> None:
    """数据过期 → WARNING（不阻塞发布）。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    macro = json.loads((LATEST / "macro.json").read_text(encoding="utf-8"))
    macro["generated_at"] = "2020-01-01T00:00:00Z"
    (latest / "macro.json").write_text(json.dumps(macro, ensure_ascii=False), encoding="utf-8")

    report = run_all(tmp_path, now=now)
    assert not any("已过期" in e for e in report.errors)
    assert any("已过期" in w for w in report.warnings), report.warnings


def test_required_file_missing(tmp_path: Path, now: datetime) -> None:
    """必填数据集缺失 → 报错。"""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)
    report = run_all(tmp_path, now=now)
    assert any("文件缺失（必填数据集）" in e for e in report.errors), report.errors
