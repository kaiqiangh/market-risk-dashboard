"""Pydantic 契约测试（T02 验收：同一 fixture 通过 Pydantic 校验 + 硬约束）。

覆盖：
- 所有核心数据集 fixture 通过对应 envelope / 自描述模型校验
- 禁隐式字段（extra="forbid"）
- 拒绝 NaN/Infinity
- 枚举/时间严格校验、数字范围校验
- schema_version 支持与向后兼容检查
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.schemas import (
    AnalysisDataset,
    BaseEnvelope,
    CalendarEnvelope,
    CryptoEnvelope,
    EquitiesEnvelope,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import SCHEMA_VERSION, is_schema_compatible

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# 数据集 key 与 Python 对齐（架构 §8.1）
ENVELOPE_FIXTURES: dict[str, type[BaseEnvelope]] = {
    "macro.json": MacroEnvelope,
    "equities.json": EquitiesEnvelope,
    "sectors.json": SectorsEnvelope,
    "crypto.json": CryptoEnvelope,
    "news.json": NewsEnvelope,
    "calendar.json": CalendarEnvelope,
    "risk.json": RiskEnvelope,
}

# 自描述契约文件（facts / analysis 不包裹 BaseEnvelope，见 contract.py 说明）
STANDALONE_FIXTURES: dict[str, type] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------- 正向：fixture 全部合法 ----------

@pytest.mark.parametrize("name,model", ENVELOPE_FIXTURES.items())
def test_envelope_fixtures_valid(name: str, model: type[BaseEnvelope]) -> None:
    parsed = model.model_validate(load_fixture(name))
    assert parsed.freshness_status in ("fresh", "delayed", "stale", "missing", "degraded")
    assert 0.0 <= parsed.data_quality <= 1.0


@pytest.mark.parametrize("name,model", STANDALONE_FIXTURES.items())
def test_standalone_fixtures_valid(name: str, model: type) -> None:
    model.model_validate(load_fixture(name))


# ---------- 负向：硬约束 ----------

def _valid_macro() -> dict:
    return load_fixture("macro.json")


def test_rejects_nan() -> None:
    data = _valid_macro()
    data["payload"]["rates"][0]["value"] = float("nan")
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)


def test_rejects_infinity() -> None:
    data = _valid_macro()
    data["payload"]["rates"][0]["value"] = float("inf")
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)


def test_rejects_extra_fields() -> None:
    data = _valid_macro()
    data["extra_key"] = "should_fail"
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)
    data2 = _valid_macro()
    data2["payload"]["rates"][0]["sneaky"] = 1
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data2)


def test_rejects_bad_enum() -> None:
    data = _valid_macro()
    data["freshness_status"] = "not_a_status"
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)


def test_rejects_bad_datetime() -> None:
    data = _valid_macro()
    data["generated_at"] = "2026-08-03 10:00:00"
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)
    data2 = _valid_macro()
    data2["generated_at"] = "2026-08-03T10:00:00+08:00"  # 非 Z 后缀
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data2)


def test_rejects_out_of_range() -> None:
    data = _valid_macro()
    data["data_quality"] = 1.5
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)
    risk = load_fixture("risk.json")
    risk["payload"]["total_score"] = 120.0
    with pytest.raises(ValidationError):
        RiskEnvelope.model_validate(risk)


def test_rejects_missing_required() -> None:
    data = _valid_macro()
    del data["generated_at"]
    with pytest.raises(ValidationError):
        MacroEnvelope.model_validate(data)


# ---------- schema_version 支持与向后兼容 ----------

def test_schema_version_supported() -> None:
    for name, model in ENVELOPE_FIXTURES.items():
        data = load_fixture(name)
        assert data["schema_version"] == SCHEMA_VERSION
        model.model_validate(data)


@pytest.mark.parametrize(
    "file_version,expected",
    [
        ("1.0.0", True),   # 当前版本
        ("1.0.1", True),   # 同 major，patch 可忽略
        ("1.1.0", False),  # 未来 minor：新字段可能不兼容（extra=forbid）
        ("2.0.0", False),  # major 不同：结构不兼容
        ("0.9.0", False),  # 更早 major
        ("not-a-version", False),
    ],
)
def test_is_schema_compatible(file_version: str, expected: bool) -> None:
    assert is_schema_compatible(file_version, SCHEMA_VERSION) is expected


# ---------- 复制隔离：负向用例不污染共享 fixture ----------

def test_fixture_files_unchanged_after_negative_tests() -> None:
    """负向用例使用深拷贝，原始 fixture 文件应保持合法。"""
    for name, model in ENVELOPE_FIXTURES.items():
        model.model_validate(load_fixture(name))
