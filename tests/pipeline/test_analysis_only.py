"""Regression for #81 — `--analysis-only` merges translations at the CALL SITE.

`merge_translations` was unit-tested with a `NewsDataset` only, which is exactly why the
envelope mismatch in `_run_analysis_only` stayed invisible through four automation
recurrences (2026-08-04 → 2026-08-07): the unit test never exercised the call site, which
handed a `NewsEnvelope` to a function expecting a `NewsDataset` (AttributeError on
`news.items`), so `news.zh-translations.json` was never merged and
`metadata/translations.json` never recorded a merge. This test drives the real function
end to end against a temp data dir.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import pipeline.analysis.contract as contract_mod
import pipeline.run as run_mod
from pipeline.lineage import fact_generation_id
from pipeline.settings import Settings
from pipeline.utils import now_utc
from tests.pipeline.factories import make_envelope, make_facts


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _build_analysis_pair(latest: Path) -> None:
    """A valid bilingual pair: the zh fixture + an en twin (identical fields; only the
    `language` field differs). Bilingual consistency requires identical market_state /
    market_regime / confidence / evidence_refs / numbers — identical is a superset."""
    zh = json.loads((_FIXTURES / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    en = copy.deepcopy(zh)
    en["language"] = "en"
    current = now_utc()
    facts = make_facts(generated_at=current)
    lineage = {
        "fact_generation_id": fact_generation_id(facts),
        "fact_generated_at": facts["generated_at"],
        "input_freshness": facts["data_freshness"],
        "pair_id": "pair-analysis-only-test",
    }
    zh["lineage"] = lineage
    en["lineage"] = lineage
    zh["generated_at"] = current
    en["generated_at"] = current
    zh["data_freshness"] = "fresh"
    en["data_freshness"] = "fresh"
    _write_json(latest / "analysis.zh-CN.json", zh)
    _write_json(latest / "analysis.en.json", en)
    _write_json(latest / "facts.json", facts)


@pytest.fixture()
def analysis_only_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A temp data dir wired into the module singletons `_run_analysis_only` reads."""
    latest = tmp_path / "latest"
    latest.mkdir(parents=True)

    settings = Settings(_env_file=None, data_dir=tmp_path, artifacts_dir=tmp_path / "artifacts")
    monkeypatch.setattr(run_mod, "settings", settings)
    monkeypatch.setattr(contract_mod, "ANALYSIS_DIR", latest)
    # INPUT_FILES was derived from the ORIGINAL ANALYSIS_DIR at import time — repoint it
    # or input_path("facts") would read the real public/data/latest/facts.json (and the
    # published-data guard would flag the read).
    monkeypatch.setattr(contract_mod, "INPUT_FILES", {"facts": latest / "facts.json", "news": latest / "news.json"})

    _build_analysis_pair(latest)

    # news.json: a NewsEnvelope whose items carry NO Chinese yet.
    news = make_envelope("news", payload={"total": 2, "updated_at": "2026-08-07T10:00:00Z", "items": [
        {"id": "en-item-1", "title": "Rates fall after payrolls", "summary": "Treasury yields eased.", "lang": "en",
         "source": "rss", "url": "https://example.com/a", "published_at": "2026-08-07T09:00:00Z", "importance": 0.8},
        {"id": "cn-item-2", "title": "美债收益率回落", "summary": "非农数据走软后收益率回落。", "lang": "zh",
         "source": "clschina", "url": "https://example.com/b", "published_at": "2026-08-07T08:00:00Z", "importance": 0.7},
    ]})
    _write_json(latest / "news.json", news)

    # news.zh-translations.json: a symmetric full pair for BOTH items (ADR-0003).
    translations = {
        "updated_at": "2026-08-07T10:05:00Z",
        "items": [
            {"id": "en-item-1", "title": "Rates fall after payrolls", "summary": "Treasury yields eased.",
             "title_zh": "非农数据走软后美债收益率回落", "summary_zh": "美债收益率走低。"},
            {"id": "cn-item-2", "title": "US Treasury yields ease", "summary": "Yields fell after soft payrolls.",
             "title_zh": "美债收益率回落", "summary_zh": "非农数据走软后收益率回落。"},
        ],
    }
    _write_json(latest / "news.zh-translations.json", translations)

    return {"latest": latest, "data_dir": tmp_path}


def test_analysis_only_merges_translations_at_the_call_site(analysis_only_env: dict[str, Path]) -> None:
    """#81: `_run_analysis_only` must hand the PAYLOAD to merge_translations (the old call
    passed the envelope → AttributeError every time) and re-wrap the result. The merge
    lands in news.json AND is recorded in metadata/translations.json."""
    rc = run_mod._run_analysis_only()

    assert rc == 0
    latest = analysis_only_env["latest"]
    news = json.loads((latest / "news.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in news["payload"]["items"]}
    assert by_id["en-item-1"]["title_zh"] == "非农数据走软后美债收益率回落"
    assert by_id["en-item-1"]["summary_zh"] == "美债收益率走低。"
    # Canonical English never overwritten (ADR-0003): the zh item keeps its zh and gains EN.
    assert by_id["cn-item-2"]["title"] == "US Treasury yields ease"
    assert by_id["cn-item-2"]["title_zh"] == "美债收益率回落"

    translations = json.loads((analysis_only_env["data_dir"] / "metadata" / "translations.json").read_text(encoding="utf-8"))
    assert translations["last_merge"]["status"] == "merged"
    assert translations["last_merge"]["merged_items"] == 2


def test_analysis_only_records_fresh_for_current_lineage(analysis_only_env: dict[str, Path]) -> None:
    assert run_mod._run_analysis_only() == 0

    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "fresh"
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "ok"


def test_malformed_replacement_restores_last_readable_pair(analysis_only_env: dict[str, Path]) -> None:
    assert run_mod._run_analysis_only() == 0
    latest = analysis_only_env["latest"]
    original = json.loads((latest / "analysis.en.json").read_text(encoding="utf-8"))
    (latest / "analysis.en.json").write_text("{not valid json", encoding="utf-8")

    assert run_mod._run_analysis_only() == 0

    restored = json.loads((latest / "analysis.en.json").read_text(encoding="utf-8"))
    assert restored["summary"] == original["summary"]
    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "degraded"
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "provider_parse_error"


def test_lineage_mismatch_is_degraded_without_losing_readable_pair(
    analysis_only_env: dict[str, Path],
) -> None:
    latest = analysis_only_env["latest"]
    assert run_mod._run_analysis_only() == 0
    en_path = latest / "analysis.en.json"
    original = json.loads(en_path.read_text(encoding="utf-8"))
    en = json.loads(en_path.read_text(encoding="utf-8"))
    en["lineage"]["fact_generation_id"] = "sha256:" + "0" * 64
    en_path.write_text(json.dumps(en, ensure_ascii=False), encoding="utf-8")

    assert run_mod._run_analysis_only() == 0

    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "degraded"
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "input_dataset_unhealthy"
    restored = json.loads(en_path.read_text(encoding="utf-8"))
    assert restored["summary"] == original["summary"]
    assert restored["lineage"]["fact_generation_id"] == original["lineage"]["fact_generation_id"]

    reports = sorted(
        (analysis_only_env["data_dir"] / "artifacts" / "logs").glob("run-report-*.json")
    )
    assert reports
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert "analysis" in report["degraded_datasets"]
    assert "input_dataset_unhealthy" in report["degraded"][0]
    assert "0" * 64 not in report["degraded"][0]


def test_missing_pair_restores_last_readable_pair(analysis_only_env: dict[str, Path]) -> None:
    assert run_mod._run_analysis_only() == 0
    latest = analysis_only_env["latest"]
    original = json.loads((latest / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    (latest / "analysis.zh-CN.json").unlink()

    assert run_mod._run_analysis_only() == 0

    restored = json.loads((latest / "analysis.zh-CN.json").read_text(encoding="utf-8"))
    assert restored["summary"] == original["summary"]
    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "all_providers_failed"


def test_degraded_fact_inputs_keep_pair_readable_but_not_fresh(
    analysis_only_env: dict[str, Path],
) -> None:
    latest = analysis_only_env["latest"]
    assert run_mod._run_analysis_only() == 0

    existing_freshness = json.loads((latest / "facts.json").read_text(encoding="utf-8"))["data_freshness"]
    degraded_freshness = {key: "degraded" for key in existing_freshness}
    facts = make_facts(generated_at=now_utc(), data_freshness=degraded_freshness)
    _write_json(latest / "facts.json", facts)
    lineage = {
        "fact_generation_id": fact_generation_id(facts),
        "fact_generated_at": facts["generated_at"],
        "input_freshness": facts["data_freshness"],
        "pair_id": "pair-analysis-only-degraded-input-test",
    }
    for language in ("zh-CN", "en"):
        path = latest / f"analysis.{language}.json"
        analysis = json.loads(path.read_text(encoding="utf-8"))
        analysis["lineage"] = lineage
        _write_json(path, analysis)

    assert run_mod._run_analysis_only() == 0

    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "degraded"
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "input_dataset_unhealthy"
    assert (latest / "analysis.zh-CN.json").exists()
    assert (latest / "analysis.en.json").exists()


def test_stale_pair_is_readable_but_not_fresh(analysis_only_env: dict[str, Path]) -> None:
    assert run_mod._run_analysis_only() == 0
    latest = analysis_only_env["latest"]
    for language in ("zh-CN", "en"):
        path = latest / f"analysis.{language}.json"
        analysis = json.loads(path.read_text(encoding="utf-8"))
        analysis["generated_at"] = "2024-01-01T00:00:00Z"
        _write_json(path, analysis)

    assert run_mod._run_analysis_only() == 0

    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "stale"
    assert freshness["datasets"]["analysis"]["reason"]["code"] == "interval_exceeded"
    assert (latest / "analysis.zh-CN.json").exists()
    assert (latest / "analysis.en.json").exists()


def test_valid_pair_recovers_after_failed_replacement(analysis_only_env: dict[str, Path]) -> None:
    assert run_mod._run_analysis_only() == 0
    latest = analysis_only_env["latest"]
    (latest / "analysis.en.json").write_text("{broken", encoding="utf-8")
    assert run_mod._run_analysis_only() == 0

    for language in ("zh-CN", "en"):
        path = latest / f"analysis.{language}.json"
        analysis = json.loads(path.read_text(encoding="utf-8"))
        analysis["summary"] = "Recovered brief."
        analysis["lineage"]["pair_id"] = "pair-analysis-only-recovered-test"
        _write_json(path, analysis)

    assert run_mod._run_analysis_only() == 0

    for language in ("zh-CN", "en"):
        analysis = json.loads((latest / f"analysis.{language}.json").read_text(encoding="utf-8"))
        assert analysis["summary"] == "Recovered brief."
    freshness = json.loads(
        (analysis_only_env["data_dir"] / "metadata" / "freshness.json").read_text(encoding="utf-8")
    )
    assert freshness["datasets"]["analysis"]["status"] == "fresh"
