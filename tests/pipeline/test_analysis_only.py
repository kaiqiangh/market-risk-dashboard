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
from pipeline.settings import Settings
from tests.pipeline.factories import make_envelope


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
    _write_json(latest / "analysis.zh-CN.json", zh)
    _write_json(latest / "analysis.en.json", en)


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
