"""T05 data validator tests (pipeline/validation/ci_checks.py).

Every test builds its own dataset with :mod:`tests.pipeline.factories` and asserts the
validator's behaviour against it. Nothing here reads the published data directory: artifacts
from the last pipeline run cannot be regenerated without API keys, and — more importantly —
they cannot be made to fail on demand, so they cannot prove that a failure mode is detected.

Covers: valid dataset passes / required dataset missing / schema + envelope validation /
NaN·Infinity / duplicate news / risk score ranges / bilingual pair, language and consistency /
freshness warnings / history slices / metadata and feeds / the published-data guard.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pipeline.validation.ci_checks import (
    ENVELOPE_MODELS,
    STANDALONE_MODELS,
    CheckReport,
    _check_risk_ranges,
    _reject_constant,
    load_json_strict,
    run_all,
)
from tests.pipeline.factories import (
    DATASET_FILENAMES,
    PAYLOAD_BUILDERS,
    REMOVE,
    ago,
    build_data_dir,
    make_analysis,
    make_envelope,
    make_facts,
    make_history_rows,
    make_metadata_freshness,
    make_news_item,
    make_news_payload,
    make_risk_dimension,
    make_risk_indicator,
    make_risk_payload,
    write_json,
)

ENVELOPE_FILENAMES: list[str] = sorted(ENVELOPE_MODELS)
STANDALONE_FILENAMES: list[str] = sorted(STANDALONE_MODELS)


# =====================================================================================
# The factory seam
#
# These tests exist so that a later ticket adding a required field to a contract fails here,
# at one obvious place, instead of failing obscurely in every downstream assertion.
# =====================================================================================


def test_synthetic_valid_dataset_passes(synthetic_data_dir: Path, now: datetime) -> None:
    """A fully synthetic tree validates clean: no errors and no warnings."""
    report = run_all(synthetic_data_dir, now=now)
    assert report.ok, f"synthetic data validation failed: {report.errors}"
    assert report.warnings == [], f"synthetic data should be warning-free: {report.warnings}"
    assert report.files_checked >= 15


def test_factory_covers_every_validated_dataset() -> None:
    """The factory registry must track the validator's registry.

    If a dataset is added to the validator without a payload builder, the suite can no longer
    build a valid tree — fail here rather than in every tree-building test.
    """
    assert set(DATASET_FILENAMES.values()) == set(ENVELOPE_MODELS)
    assert set(DATASET_FILENAMES) == set(PAYLOAD_BUILDERS)


@pytest.mark.parametrize("filename", ENVELOPE_FILENAMES)
def test_make_envelope_validates_against_real_model(filename: str) -> None:
    """make_envelope() output satisfies the production Pydantic contract for every dataset."""
    model, _dataset_key = ENVELOPE_MODELS[filename]
    model.model_validate(make_envelope(filename))


@pytest.mark.parametrize("filename", STANDALONE_FILENAMES)
def test_standalone_factories_validate_against_real_model(filename: str) -> None:
    """facts.json and both analysis files satisfy their production contracts."""
    builders: dict[str, Any] = {
        "facts.json": make_facts,
        "analysis.zh-CN.json": lambda: make_analysis(language="zh-CN"),
        "analysis.en.json": lambda: make_analysis(language="en"),
    }
    STANDALONE_MODELS[filename].model_validate(builders[filename]())


def test_make_envelope_accepts_dataset_name_or_filename() -> None:
    """`make_envelope("news")` and `make_envelope("news.json")` are the same document."""
    assert make_envelope("news") == make_envelope("news.json")


def test_make_envelope_override_replaces_field() -> None:
    """Any envelope field can be overridden, which is how invalid cases are constructed."""
    envelope = make_envelope("macro", data_quality=0.4, freshness_status="degraded")
    assert envelope["data_quality"] == 0.4
    assert envelope["freshness_status"] == "degraded"


def test_make_envelope_remove_drops_field() -> None:
    """REMOVE deletes a key, so a test can build a document missing a required field."""
    envelope = make_envelope("macro", data_quality=REMOVE)
    assert "data_quality" not in envelope
    assert "generated_at" in envelope


def test_make_envelope_payload_override_is_honoured() -> None:
    """An explicit payload replaces the default one rather than merging with it."""
    envelope = make_envelope("news", payload=make_news_payload(items=[]))
    assert envelope["payload"]["items"] == []
    assert envelope["payload"]["total"] == 0


def test_make_envelope_rejects_unknown_dataset() -> None:
    """A typo in a dataset name fails loudly instead of yielding an empty document."""
    with pytest.raises(KeyError, match="unknown dataset"):
        make_envelope("macros")


def test_build_data_dir_writes_only_under_its_root(tmp_path: Path) -> None:
    """The synthetic tree is entirely self-contained under the directory it is given."""
    root = build_data_dir(tmp_path / "data")
    written = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    expected = {f"latest/{name}" for name in ENVELOPE_FILENAMES} | {
        f"latest/{name}" for name in STANDALONE_FILENAMES
    }
    expected |= {
        f"history/{series}/{slice_name}.json"
        for series in ("risk", "market")
        for slice_name in ("30d", "90d", "daily", "index")
    }
    expected |= {
        "metadata/freshness.json",
        "metadata/sources.json",
        "metadata/schema-version.json",
        "feeds/fedwatch-history.json",
    }
    assert written == expected


def test_build_data_dir_can_omit_a_file(make_data_dir: Any) -> None:
    """REMOVE at tree level omits a file — the seam for every 'missing file' case."""
    root = make_data_dir(latest={"news.json": REMOVE})
    assert not (root / "latest" / "news.json").exists()
    assert (root / "latest" / "macro.json").exists()


# =====================================================================================
# Required files
# =====================================================================================


def test_required_file_missing(empty_data_dir: Path, now: datetime) -> None:
    """Required dataset missing → error."""
    report = run_all(empty_data_dir, now=now)
    assert any("file missing (required dataset)" in e for e in report.errors), report.errors


@pytest.mark.parametrize("filename", ENVELOPE_FILENAMES)
def test_missing_single_dataset_detected(filename: str, make_data_dir: Any, now: datetime) -> None:
    """Each required dataset is individually required, not merely required as a group."""
    root = make_data_dir(latest={filename: REMOVE})
    report = run_all(root, now=now)
    assert f"{filename}: file missing (required dataset)" in report.errors, report.errors


def test_facts_missing_is_error(make_data_dir: Any, now: datetime) -> None:
    """facts.json is produced on every pipeline run, so its absence is an error."""
    root = make_data_dir(latest={"facts.json": REMOVE})
    report = run_all(root, now=now)
    assert any("facts.json: file missing" in e for e in report.errors), report.errors


def test_latest_directory_missing_detected(tmp_path: Path, now: datetime) -> None:
    """No latest/ directory at all → a single explicit error."""
    report = run_all(tmp_path / "nothing-here", now=now)
    assert any("latest directory missing" in e for e in report.errors), report.errors


# =====================================================================================
# Schema and envelope validation
# =====================================================================================


def test_extra_field_rejected(synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime) -> None:
    """Contracts forbid implicit fields (extra="forbid")."""
    write_json(synthetic_latest_dir / "macro.json", make_envelope("macro", unexpected_field="x"))
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json: schema validation failed" in e for e in report.errors), report.errors


def test_missing_required_envelope_field_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """An envelope missing data_quality fails schema validation."""
    write_json(synthetic_latest_dir / "macro.json", make_envelope("macro", data_quality=REMOVE))
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json: schema validation failed" in e for e in report.errors), report.errors


def test_incompatible_schema_version_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """A major-version bump in a published file must block publishing."""
    write_json(synthetic_latest_dir / "macro.json", make_envelope("macro", schema_version="2.0.0"))
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json: schema_version 2.0.0 incompatible" in e for e in report.errors), report.errors


def test_non_utc_timestamp_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """generated_at must be ISO 8601 UTC with a trailing Z."""
    write_json(
        synthetic_latest_dir / "macro.json",
        make_envelope("macro", generated_at="2026-08-04 12:00:00+02:00"),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json" in e and "generated_at" in e for e in report.errors), report.errors


def test_data_quality_out_of_range_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """data_quality must sit in [0,1]."""
    write_json(synthetic_latest_dir / "macro.json", make_envelope("macro", data_quality=1.5))
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json" in e and "data_quality" in e for e in report.errors), report.errors


def test_invalid_freshness_status_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """freshness_status must be one of the five states."""
    write_json(synthetic_latest_dir / "macro.json", make_envelope("macro", freshness_status="unknown"))
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json" in e and "freshness_status" in e for e in report.errors), report.errors


# =====================================================================================
# NaN / Infinity
# =====================================================================================


def test_nan_infinity_rejected(tmp_path: Path) -> None:
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


def test_nan_in_published_file_is_an_error(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """A NaN inside a real dataset file surfaces as an error, not an exception."""
    (synthetic_latest_dir / "macro.json").write_text(
        '{"generated_at": "2026-08-04T12:00:00Z", "data_quality": NaN}', encoding="utf-8"
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json: unable to read/parse JSON" in e for e in report.errors), report.errors


def test_malformed_json_is_an_error(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Truncated JSON is reported rather than crashing the run."""
    (synthetic_latest_dir / "macro.json").write_text('{"generated_at":', encoding="utf-8")
    report = run_all(synthetic_data_dir, now=now)
    assert any("macro.json: unable to read/parse JSON" in e for e in report.errors), report.errors


# =====================================================================================
# Duplicate news
# =====================================================================================


def test_duplicate_news_id_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Duplicate news id must be reported."""
    duplicated = make_news_item(id="duplicate-id")
    payload = make_news_payload(
        items=[duplicated, make_news_item(id="duplicate-id", title="A different headline entirely")]
    )
    write_json(synthetic_latest_dir / "news.json", make_envelope("news", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("duplicate news id 'duplicate-id'" in e for e in report.errors), report.errors


def test_duplicate_news_signature_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Distinct ids but identical (title+source+published_at) is still a duplicate."""
    payload = make_news_payload(
        items=[make_news_item(id="first"), make_news_item(id="second")]
    )
    write_json(synthetic_latest_dir / "news.json", make_envelope("news", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("duplicate news (title+source+published_at)" in e for e in report.errors), report.errors


def test_distinct_news_items_are_not_flagged(synthetic_data_dir: Path, now: datetime) -> None:
    """The default news fixture has genuinely distinct items — no false positive."""
    report = run_all(synthetic_data_dir, now=now)
    assert not any("duplicate news" in e for e in report.errors), report.errors


# =====================================================================================
# Risk score ranges
# =====================================================================================


def test_risk_score_range_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Risk score out of [0,100] must be reported."""
    payload = make_risk_payload(total_score=150.0)
    write_json(synthetic_latest_dir / "risk.json", make_envelope("risk", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("total_score" in e and "150" in e for e in report.errors), report.errors


def test_risk_dimension_score_range_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """A dimension score out of [0,100] must be reported."""
    payload = make_risk_payload(dimensions=[make_risk_dimension(score=150.0)])
    write_json(synthetic_latest_dir / "risk.json", make_envelope("risk", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("risk.json" in e and "150" in e for e in report.errors), report.errors


def test_risk_indicator_score_range_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """A sub-indicator risk_score out of [0,100] must be reported."""
    payload = make_risk_payload(
        dimensions=[make_risk_dimension(indicators=[make_risk_indicator(risk_score=150.0)])]
    )
    write_json(synthetic_latest_dir / "risk.json", make_envelope("risk", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("risk.json" in e and "150" in e for e in report.errors), report.errors


def test_risk_confidence_range_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """confidence is a ratio and must sit in [0,1]."""
    payload = make_risk_payload(confidence=1.5)
    write_json(synthetic_latest_dir / "risk.json", make_envelope("risk", payload=payload))

    report = run_all(synthetic_data_dir, now=now)
    assert any("risk.json" in e and "confidence" in e for e in report.errors), report.errors


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(make_risk_payload(total_score=150.0), "total_score", id="total_score"),
        pytest.param(
            make_risk_payload(dimensions=[make_risk_dimension(score=150.0)]),
            "score out of range",
            id="dimension_score",
        ),
        pytest.param(
            make_risk_payload(
                dimensions=[make_risk_dimension(indicators=[make_risk_indicator(risk_score=150.0)])]
            ),
            "risk_score out of range",
            id="indicator_risk_score",
        ),
        pytest.param(make_risk_payload(confidence=1.5), "confidence out of range", id="confidence"),
        pytest.param(
            make_risk_payload(total_score=REMOVE), "unable to re-check", id="malformed_structure"
        ),
    ],
)
def test_risk_range_recheck_is_defence_in_depth(payload: dict[str, Any], expected: str) -> None:
    """The explicit range re-check is exercised directly.

    Through run_all these payloads are rejected by Pydantic first, so the re-check never sees
    them. Calling it directly keeps the branch honest, since it is the safety net for the day a
    Field bound is relaxed.
    """
    report = CheckReport()
    _check_risk_ranges(payload, report, "risk.json")
    assert any(expected in e for e in report.errors), report.errors


# =====================================================================================
# Bilingual analysis
# =====================================================================================


@pytest.mark.parametrize("missing_side", ["analysis.en.json", "analysis.zh-CN.json"])
def test_analysis_pair_missing_one_side(make_data_dir: Any, now: datetime, missing_side: str) -> None:
    """Either side missing → bilingual missing error (#73: both branches pinned)."""
    root = make_data_dir(latest={missing_side: REMOVE})
    report = run_all(root, now=now)
    assert any("missing bilingual analysis file" in e for e in report.errors), report.errors


def test_make_analysis_language_is_overridable() -> None:
    """#73 wart: every field of every builder is overridable the same way.

    `make_analysis` used to take `language` positionally, so `make_analysis("en",
    language="fr")` raised `TypeError: got multiple values`. `language` is keyword-only now:
    the keyword form works, and the positional form is a clean signature error.
    """
    assert make_analysis(language="fr")["language"] == "fr"
    assert make_analysis(language="en")["language"] == "en"
    with pytest.raises(TypeError) as excinfo:
        make_analysis("en", language="fr")  # type: ignore[call-arg]
    assert "multiple values for argument" not in str(excinfo.value)


def test_unknown_language_key_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Unknown language analysis.fr.json → error."""
    write_json(synthetic_latest_dir / "analysis.fr.json", make_analysis(language="fr"))
    report = run_all(synthetic_data_dir, now=now)
    assert any("unknown language key" in e for e in report.errors), report.errors


def test_bilingual_inconsistency_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Bilingual market_state mismatch → error."""
    write_json(
        synthetic_latest_dir / "analysis.en.json",
        make_analysis(language="en", market_state="different_value"),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any(
        "AI bilingual conclusion mismatch" in e and "market_state" in e for e in report.errors
    ), report.errors


def test_bilingual_regime_mismatch_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """The two languages must agree on the market regime."""
    write_json(synthetic_latest_dir / "analysis.en.json", make_analysis(language="en", market_regime="crisis"))
    report = run_all(synthetic_data_dir, now=now)
    assert any("market_regime mismatch" in e for e in report.errors), report.errors


def test_bilingual_confidence_mismatch_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """The two languages must report the same confidence."""
    write_json(synthetic_latest_dir / "analysis.en.json", make_analysis(language="en", confidence=0.31))
    report = run_all(synthetic_data_dir, now=now)
    assert any("confidence mismatch" in e for e in report.errors), report.errors


def test_bilingual_evidence_refs_mismatch_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Both languages must cite exactly the same evidence."""
    write_json(
        synthetic_latest_dir / "analysis.en.json",
        make_analysis(language="en", top_risk_drivers=[{"claim": "Unsourced claim.", "evidence_refs": []}]),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("evidence_refs set mismatch" in e for e in report.errors), report.errors


def test_bilingual_list_length_mismatch_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Parallel lists must be structurally equivalent across languages."""
    write_json(synthetic_latest_dir / "analysis.en.json", make_analysis(language="en", watch_next=[]))
    report = run_all(synthetic_data_dir, now=now)
    assert any("watch_next length mismatch" in e for e in report.errors), report.errors


def test_bilingual_number_mismatch_detected(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Only the prose language may differ; the numbers inside it may not."""
    write_json(
        synthetic_latest_dir / "analysis.en.json",
        make_analysis(language="en", summary="Total score 99.9 places the market in caution."),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("text number mismatch" in e for e in report.errors), report.errors


def test_both_analysis_missing_is_degraded_warning(make_data_dir: Any, now: datetime) -> None:
    """No AI briefing at all is degraded mode, a warning — it must not block publishing."""
    root = make_data_dir(
        latest={"analysis.zh-CN.json": REMOVE, "analysis.en.json": REMOVE}
    )
    report = run_all(root, now=now)
    assert report.ok, report.errors
    assert any("AI briefing not generated" in w for w in report.warnings), report.warnings


def test_unparseable_analysis_reported_as_bilingual_failure(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """A corrupt analysis file fails the bilingual stage instead of crashing the run."""
    (synthetic_latest_dir / "analysis.en.json").write_text("{", encoding="utf-8")
    report = run_all(synthetic_data_dir, now=now)
    assert any("AI bilingual validation failed" in e for e in report.errors), report.errors


# =====================================================================================
# Freshness — degradation must be provable, which is only possible with synthetic input
# =====================================================================================


def test_stale_is_warning_not_error(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Stale data → WARNING (does not block publishing)."""
    write_json(
        synthetic_latest_dir / "macro.json",
        make_envelope("macro", generated_at=ago(minutes=60 * 24 * 365)),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert not any("is stale" in e for e in report.errors), report.errors
    assert any("is stale" in w for w in report.warnings), report.warnings
    assert report.ok


def test_delayed_is_warning_not_error(
    synthetic_latest_dir: Path, synthetic_data_dir: Path, now: datetime
) -> None:
    """Between 1.5x and 3x the expected interval is delayed, also only a warning."""
    write_json(
        synthetic_latest_dir / "macro.json", make_envelope("macro", generated_at=ago(minutes=500))
    )
    report = run_all(synthetic_data_dir, now=now)
    assert not any("is delayed" in e for e in report.errors), report.errors
    assert any("is delayed" in w for w in report.warnings), report.warnings
    assert report.ok


def test_fresh_data_produces_no_freshness_diagnostic(synthetic_data_dir: Path, now: datetime) -> None:
    """The baseline fixture is inside the expected interval — no false staleness."""
    report = run_all(synthetic_data_dir, now=now)
    assert not any("is stale" in w or "is delayed" in w for w in report.warnings), report.warnings


# =====================================================================================
# History slices
# =====================================================================================


def test_history_missing_is_warning(make_data_dir: Any, now: datetime) -> None:
    """A missing history slice is a warm-up condition, not a publishing blocker."""
    root = make_data_dir(support={"history/risk/30d.json": REMOVE})
    report = run_all(root, now=now)
    assert report.ok, report.errors
    assert any("history/risk/30d.json missing" in w for w in report.warnings), report.warnings


def test_history_invalid_date_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """History rows must carry a YYYY-MM-DD date."""
    write_json(
        synthetic_data_dir / "history" / "risk" / "30d.json",
        [{"date": "04/08/2026", "total_score": 62.5}],
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("invalid row date" in e for e in report.errors), report.errors


def test_history_score_out_of_range_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """History total_score must sit in [0,100]."""
    rows = make_history_rows(days=1)
    rows[0]["total_score"] = 150.0
    write_json(synthetic_data_dir / "history" / "market" / "daily.json", rows)
    report = run_all(synthetic_data_dir, now=now)
    assert any("total_score out of range" in e for e in report.errors), report.errors


def test_history_non_array_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """A history slice must be a top-level array."""
    write_json(synthetic_data_dir / "history" / "risk" / "90d.json", {"rows": []})
    report = run_all(synthetic_data_dir, now=now)
    assert any("top level should be an array" in e for e in report.errors), report.errors


def test_history_row_not_object_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """Each history row must be an object."""
    write_json(synthetic_data_dir / "history" / "risk" / "daily.json", ["2026-08-04"])
    report = run_all(synthetic_data_dir, now=now)
    assert any("row is not an object" in e for e in report.errors), report.errors


def test_history_non_numeric_score_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """A non-numeric total_score is reported rather than raising."""
    write_json(
        synthetic_data_dir / "history" / "market" / "30d.json",
        [{"date": "2026-08-04", "total_score": "high"}],
    )
    report = run_all(synthetic_data_dir, now=now)
    assert any("invalid total_score" in e for e in report.errors), report.errors


def test_history_index_parse_failure_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """A corrupt history index is an error."""
    (synthetic_data_dir / "history" / "risk" / "index.json").write_text("{", encoding="utf-8")
    report = run_all(synthetic_data_dir, now=now)
    assert any("history/risk/index.json: parse failed" in e for e in report.errors), report.errors


# =====================================================================================
# metadata/ and feeds/
# =====================================================================================


def test_metadata_missing_is_warning(make_data_dir: Any, now: datetime) -> None:
    """Status-page metadata is informational: missing is a warning."""
    root = make_data_dir(support={"metadata/sources.json": REMOVE})
    report = run_all(root, now=now)
    assert report.ok, report.errors
    assert any("metadata/sources.json missing" in w for w in report.warnings), report.warnings


def test_metadata_missing_key_is_warning(synthetic_data_dir: Path, now: datetime) -> None:
    """A metadata file missing an expected key warns rather than blocking."""
    write_json(
        synthetic_data_dir / "metadata" / "freshness.json",
        make_metadata_freshness(datasets=REMOVE),
    )
    report = run_all(synthetic_data_dir, now=now)
    assert report.ok, report.errors
    assert any("missing field 'datasets'" in w for w in report.warnings), report.warnings


def test_metadata_parse_failure_detected(synthetic_data_dir: Path, now: datetime) -> None:
    """A corrupt metadata file is an error, since the status page would break on it."""
    (synthetic_data_dir / "metadata" / "freshness.json").write_text("{", encoding="utf-8")
    report = run_all(synthetic_data_dir, now=now)
    assert any("metadata/freshness.json: parse failed" in e for e in report.errors), report.errors


def test_feeds_missing_is_warning(make_data_dir: Any, now: datetime) -> None:
    """The FedWatch feed is optional for a code change."""
    root = make_data_dir(support={"feeds/fedwatch-history.json": REMOVE})
    report = run_all(root, now=now)
    assert report.ok, report.errors
    assert any("feeds/fedwatch-history.json missing" in w for w in report.warnings), report.warnings


# =====================================================================================
# Report semantics
# =====================================================================================


def test_warnings_alone_do_not_block_publishing(make_data_dir: Any, now: datetime) -> None:
    """A report with warnings and no errors still passes — the documented exit-code contract."""
    root = make_data_dir(
        latest={"analysis.zh-CN.json": REMOVE, "analysis.en.json": REMOVE},
        support={"history/risk/30d.json": REMOVE, "metadata/sources.json": REMOVE},
    )
    report = run_all(root, now=now)
    assert report.warnings
    assert report.ok


def test_files_checked_counts_every_validated_file(synthetic_data_dir: Path, now: datetime) -> None:
    """files_checked covers latest/, history/ and metadata/ — not just latest/."""
    report = run_all(synthetic_data_dir, now=now)
    assert report.files_checked == len(ENVELOPE_FILENAMES) + len(STANDALONE_FILENAMES) + 8 + 4


# =====================================================================================
# The guard
# =====================================================================================


def test_suite_does_not_read_published_data(published_data_reads: list[str]) -> None:
    """No test may open a file in the published data directory.

    Published artifacts cannot be regenerated without API keys and cannot be made to fail on
    demand. Any read of them re-couples the suite to the last pipeline run, which is exactly
    what this module was rewritten to remove.
    """
    assert published_data_reads == [], (
        "the suite opened published data files: "
        + ", ".join(sorted(set(published_data_reads)))
        + " — build the data with tests/pipeline/factories.py instead"
    )
