"""Pydantic contract tests (T02 acceptance: the same fixture passes Pydantic validation + hard constraints).

Covers:
- All core dataset fixtures pass the corresponding envelope / self-describing model validation
- No implicit fields (extra="forbid")
- Rejects NaN/Infinity
- Strict enum/time validation, numeric range validation
- schema_version support and backward-compatibility check
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
    DashboardEnvelope,
    EquitiesEnvelope,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import SCHEMA_VERSION, is_schema_compatible

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

# Dataset keys aligned with Python (architecture §8.1)
ENVELOPE_FIXTURES: dict[str, type[BaseEnvelope]] = {
    "macro.json": MacroEnvelope,
    "equities.json": EquitiesEnvelope,
    "sectors.json": SectorsEnvelope,
    "crypto.json": CryptoEnvelope,
    "news.json": NewsEnvelope,
    "calendar.json": CalendarEnvelope,
    "risk.json": RiskEnvelope,
    "dashboard.json": DashboardEnvelope,
}

# Self-describing contract files (facts / analysis are not wrapped in BaseEnvelope; see contract.py)
STANDALONE_FIXTURES: dict[str, type] = {
    "facts.json": FactLayer,
    "analysis.zh-CN.json": AnalysisDataset,
    "analysis.en.json": AnalysisDataset,
}


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------- Positive: all fixtures valid ----------

@pytest.mark.parametrize("name,model", ENVELOPE_FIXTURES.items())
def test_envelope_fixtures_valid(name: str, model: type[BaseEnvelope]) -> None:
    parsed = model.model_validate(load_fixture(name))
    assert parsed.freshness_status in ("fresh", "delayed", "stale", "missing", "degraded")
    assert 0.0 <= parsed.data_quality <= 1.0


@pytest.mark.parametrize("name,model", STANDALONE_FIXTURES.items())
def test_standalone_fixtures_valid(name: str, model: type) -> None:
    model.model_validate(load_fixture(name))


# ---------- Negative: hard constraints ----------

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
    data2["generated_at"] = "2026-08-03T10:00:00+08:00"  # non-Z suffix
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


# ---------- schema_version support and backward compatibility ----------

def test_schema_version_supported() -> None:
    for name, model in ENVELOPE_FIXTURES.items():
        data = load_fixture(name)
        assert data["schema_version"] == SCHEMA_VERSION
        model.model_validate(data)


@pytest.mark.parametrize(
    "file_version,expected",
    [
        ("1.0.0", True),   # current version
        ("1.0.1", True),   # same major, patch ignored
        ("1.1.0", False),  # future minor: new fields may be incompatible (extra=forbid)
        ("2.0.0", False),  # different major: structure incompatible
        ("0.9.0", False),  # earlier major
        ("not-a-version", False),
    ],
)
def test_is_schema_compatible(file_version: str, expected: bool) -> None:
    assert is_schema_compatible(file_version, SCHEMA_VERSION) is expected


# ---------- Copy isolation: negative cases do not pollute shared fixtures ----------

def test_fixture_files_unchanged_after_negative_tests() -> None:
    """Negative cases use deep copies; the original fixture files must remain valid."""
    for name, model in ENVELOPE_FIXTURES.items():
        model.model_validate(load_fixture(name))
