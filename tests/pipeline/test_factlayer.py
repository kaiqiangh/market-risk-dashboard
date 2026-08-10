"""Fact-layer rebuild tests (#63 defect 4).

`python -m pipeline.run --fact-layer` is the one recovery path that does not require
re-fetching from providers. It raised `NameError` on every real invocation because
`pipeline/run.py:578` evaluated `SectorsEnvelope` without importing it.

**The trap these tests are written around.** That line is guarded by
``... if sectors_data else None``, so the undefined name is only resolved when
``latest/sectors.json`` exists. A synthetic tree that omits `sectors.json` short-circuits
the expression, never resolves the name, and passes against unfixed code — a test that
proves nothing. Every test here therefore builds a `latest/` tree *including* a valid
`sectors.json`, and asserts the rebuilt fact layer carries the sectors contribution, so
it cannot pass by skipping the branch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.settings import Settings
from tests.pipeline.factories import build_data_dir, make_envelope

#: Datasets `_run_fact_layer_only` requires before it will rebuild.
REQUIRED_DATASETS = ("macro", "equities", "crypto", "news", "calendar", "risk")


@pytest.fixture()
def fact_layer_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point `pipeline.run` at a synthetic published tree and return its data dir.

    `pipeline.run` binds the settings singleton at import time, so the fixture rebinds
    that module's `settings` rather than mutating the global one.
    """
    import pipeline.run as run_module

    data_dir = build_data_dir(tmp_path / "data")
    synthetic = Settings(
        _env_file=None,
        data_dir=data_dir,
        artifacts_dir=tmp_path / "artifacts",
    )
    monkeypatch.setattr(run_module, "settings", synthetic)
    return data_dir


def _facts(data_dir: Path) -> dict[str, Any]:
    return json.loads((data_dir / "latest" / "facts.json").read_text(encoding="utf-8"))


def test_synthetic_tree_includes_sectors(fact_layer_env: Path) -> None:
    """Guard the guard: if this tree ever loses sectors.json, the rebuild test goes vacuous.

    `_run_fact_layer_only` only resolves `SectorsEnvelope` when `latest/sectors.json` is
    truthy. This test exists so that a future edit to the factory defaults cannot silently
    turn `test_fact_layer_only_rebuild_succeeds` into a test of the short-circuit path.
    """
    sectors_path = fact_layer_env / "latest" / "sectors.json"
    assert sectors_path.exists(), "the synthetic tree must contain sectors.json or the rebuild test proves nothing"

    document = json.loads(sectors_path.read_text(encoding="utf-8"))
    assert document.get("payload"), "sectors.json must be non-empty, or run.py short-circuits past the defect"


def test_fact_layer_only_rebuild_succeeds(fact_layer_env: Path) -> None:
    """`--fact-layer` completes against a synthetic latest/ tree instead of raising NameError."""
    from pipeline.run import _run_fact_layer_only

    ok, error = _run_fact_layer_only()

    assert ok is True, f"fact-layer rebuild failed: {error}"
    assert error is None

    facts = _facts(fact_layer_env)
    # The sectors contribution must be present — this is what makes the test non-vacuous.
    # `FactLayerBuilder.build` only adds this key when `sectors is not None`, so its
    # presence proves the branch holding the defect was executed.
    assert "sectors" in facts["data_freshness"], (
        "rebuilt facts carry no sectors contribution — run.py short-circuited past the "
        "SectorsEnvelope branch, so this test would pass on unfixed code"
    )
    assert facts["data_freshness"]["sectors"] == "fresh"

    for dataset in REQUIRED_DATASETS:
        assert dataset in facts["data_freshness"], f"rebuilt facts missing {dataset}"


def test_fact_layer_rebuild_resolves_sectors_envelope(fact_layer_env: Path) -> None:
    """The defect itself: evaluating the sectors branch must not raise NameError.

    Asserting on the exception type rather than the return value pins the specific
    regression. `_run_fact_layer_only` returns `(False, reason)` for *expected* problems
    such as missing inputs; an undefined name escapes as a raise, so a broad
    `assert ok` would not distinguish the two.
    """
    from pipeline.run import _run_fact_layer_only

    try:
        ok, _ = _run_fact_layer_only()
    except NameError as exc:  # pragma: no cover - the pre-#63 behaviour
        pytest.fail(f"fact-layer rebuild raised on an undefined name: {exc}")

    assert ok is True


def test_fact_layer_rebuild_writes_facts_and_freshness(fact_layer_env: Path) -> None:
    """A successful rebuild publishes facts.json and marks it fresh."""
    from pipeline.run import _run_fact_layer_only

    ok, _ = _run_fact_layer_only()
    assert ok is True

    facts_path = fact_layer_env / "latest" / "facts.json"
    assert facts_path.exists()
    facts = _facts(fact_layer_env)
    assert facts["schema_version"]
    assert facts["risk"], "rebuilt facts must carry the risk payload"

    freshness = json.loads((fact_layer_env / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    entry = freshness["datasets"]["factlayer"]
    assert entry["status"] == "fresh"
    # #89: the reason is a structured {code, detail}, not free text. The status is never its
    # own explanation — that is how eight datasets came to publish reason "degraded".
    assert entry["reason"]["code"] == "ok"
    assert entry["reason"]["detail"] == "rebuilt from latest/*.json"

    # Every registered dataset appears, always. An absent key used to be indistinguishable
    # from a healthy one.
    from pipeline.schemas import registry

    assert set(freshness["datasets"]) == set(registry.CANONICAL_KEYS)


def test_fact_layer_rebuild_without_sectors_still_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sectors is optional: absent sectors.json rebuilds without it, and says so.

    This is the short-circuit path. It is legitimate behaviour — `FactLayerBuilder.build`
    takes `sectors` as optional — but it must be tested *separately* from the defect, or
    it masks it.
    """
    import pipeline.run as run_module

    data_dir = build_data_dir(tmp_path / "data")
    (data_dir / "latest" / "sectors.json").unlink()
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=tmp_path / "artifacts"),
    )

    ok, error = run_module._run_fact_layer_only()

    assert ok is True, f"rebuild without sectors failed: {error}"
    facts = _facts(data_dir)
    assert "sectors" not in facts["data_freshness"]


def test_fact_layer_rebuild_reports_missing_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A required dataset missing is an expected failure: return a reason, do not raise."""
    import pipeline.run as run_module

    data_dir = build_data_dir(tmp_path / "data")
    (data_dir / "latest" / "risk.json").unlink()
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=tmp_path / "artifacts"),
    )

    ok, error = run_module._run_fact_layer_only()

    assert ok is False
    assert error is not None
    assert "latest" in error


def test_fact_layer_rebuild_is_idempotent(fact_layer_env: Path) -> None:
    """Rebuilding twice from unchanged inputs yields the same facts, timestamps aside."""
    from pipeline.run import _run_fact_layer_only

    assert _run_fact_layer_only()[0] is True
    first = _facts(fact_layer_env)
    assert _run_fact_layer_only()[0] is True
    second = _facts(fact_layer_env)

    volatile = {"generated_at"}
    assert {k: v for k, v in first.items() if k not in volatile} == {
        k: v for k, v in second.items() if k not in volatile
    }


def test_fact_layer_rebuild_rejects_corrupt_sectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt sectors.json is named, not silently skipped (#63 defect 2 reaching the rebuild).

    Before #63 `_read_json` swallowed `JSONDecodeError` and returned `None`, which made a
    corrupt sectors file indistinguishable from an absent one — the rebuild would quietly
    publish facts with no sectors contribution.
    """
    import pipeline.run as run_module
    from pipeline.storage.writer import CorruptDataError

    data_dir = build_data_dir(tmp_path / "data")
    (data_dir / "latest" / "sectors.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=tmp_path / "artifacts"),
    )

    with pytest.raises(CorruptDataError) as excinfo:
        run_module._run_fact_layer_only()

    assert "sectors.json" in str(excinfo.value)


def test_fact_layer_rebuild_uses_overridden_sectors_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rebuild reads the sectors file it was given, rather than a default."""
    import pipeline.run as run_module

    data_dir = build_data_dir(
        tmp_path / "data",
        latest={"sectors.json": make_envelope("sectors", freshness_status="degraded")},
    )
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=tmp_path / "artifacts"),
    )

    ok, error = run_module._run_fact_layer_only()

    assert ok is True, f"rebuild failed: {error}"
    assert _facts(data_dir)["data_freshness"]["sectors"] == "degraded"


def test_rebuild_preserves_fetched_at(fact_layer_env: Path) -> None:
    """Ruling E: a rebuild preserves the original fetched_at; it never re-stamps as fresh.

    The fact layer is an aggregation of observed datasets, not an observation itself.
    `--fact-layer` reads existing latest/*.json and reassembles facts.json; the rebuilt
    facts must carry the original generated_at (recomputed status from it), not `now`.
    """
    import pipeline.run as run_module

    original = _facts(fact_layer_env)
    original_fetched_at = str(original["generated_at"])

    assert run_module.main(["--fact-layer"]) == 0

    rebuilt = _facts(fact_layer_env)
    assert str(rebuilt["generated_at"]) == original_fetched_at, (
        "a rebuild must preserve the original fetched_at, got "
        f"{rebuilt['generated_at']!r} instead of {original_fetched_at!r}"
    )


def test_market_summary_carries_sector_performance_and_prompt_labels_it() -> None:
    """#98: the 20-theme taxonomy reaches the AI brief — the fact layer carries
    sector/theme keys + numbers (C-1, no display labels in payloads) and build_prompt
    resolves the EN labels from the same themes.json the frontend renders."""
    from pipeline.analysis.build_prompt import _render_facts
    from pipeline.factlayer.builder import FactLayerBuilder
    from pipeline.schemas import CryptoEnvelope, EquitiesEnvelope, FactLayer, MacroEnvelope, NewsEnvelope, RiskEnvelope, CalendarEnvelope, SectorsEnvelope
    from pipeline.schemas.sectors import SectorItem, SectorsDataset
    from pipeline.settings import Settings
    from tests.pipeline.factories import make_envelope

    builder = FactLayerBuilder()
    equities = make_envelope("equities")

    sectors = SectorsEnvelope.model_validate({
        **make_envelope("sectors"),
        "payload": SectorsDataset(
            sectors=[SectorItem(key="semis", change_1d=2.5)],
            themes=[SectorItem(key="ai_infrastructure", change_1d=-1.2)],
            memory=None,
        ).model_dump(),
    })
    facts: FactLayer = builder.build(
        risk=RiskEnvelope.model_validate(make_envelope("risk")),
        macro=MacroEnvelope.model_validate(make_envelope("macro")),
        equities=EquitiesEnvelope.model_validate(equities),
        crypto=CryptoEnvelope.model_validate(make_envelope("crypto")),
        news=NewsEnvelope.model_validate(make_envelope("news")),
        calendar=CalendarEnvelope.model_validate(make_envelope("calendar")),
        sectors=sectors,
    )
    perf = facts.market_summary["sector_performance"]
    assert {"key": "semis", "change_1d": 2.5} in perf
    assert {"key": "ai_infrastructure", "change_1d": -1.2} in perf

    # The sector/theme moves are citable: they land in the evidence_index (#98 — the
    # brief's rule is "may ONLY cite entries present in the evidence_index").
    assert "ev_sector_semis" in facts.evidence_index
    assert facts.evidence_index["ev_sector_ai_infrastructure"].value == -1.2

    prompt_en = _render_facts(facts, "en")
    assert "Sector performance (1d)" in prompt_en
    assert "Semis Leaders: +2.50%" in prompt_en  # EN label resolved from en themes.json
    assert "AI Infrastructure: -1.20%" in prompt_en

    # The zh-CN brief resolves the zh labels — no EN leak into the zh prompt (#98 review).
    prompt_zh = _render_facts(facts, "zh-CN")
    assert "板块表现（1日）" in prompt_zh
    assert "半导体龙头: +2.50%" in prompt_zh


def test_evidence_does_not_fabricate_missing_source_timestamps() -> None:
    """Evidence may be undated when its dataset has no honest source observation time."""
    from pipeline.factlayer.builder import FactLayerBuilder
    from pipeline.schemas import (
        CalendarEnvelope,
        CryptoEnvelope,
        EquitiesEnvelope,
        MacroEnvelope,
        NewsEnvelope,
        RiskEnvelope,
        SectorsEnvelope,
    )
    from tests.pipeline.factories import make_envelope

    def without_source(name: str) -> dict[str, Any]:
        return {**make_envelope(name), "source_updated_at": None}

    facts = FactLayerBuilder().build(
        risk=RiskEnvelope.model_validate(without_source("risk")),
        macro=MacroEnvelope.model_validate(without_source("macro")),
        equities=EquitiesEnvelope.model_validate(without_source("equities")),
        crypto=CryptoEnvelope.model_validate(without_source("crypto")),
        news=NewsEnvelope.model_validate(without_source("news")),
        calendar=CalendarEnvelope.model_validate(without_source("calendar")),
        sectors=SectorsEnvelope.model_validate(without_source("sectors")),
    )

    for key in ("ev_total_score", "ev_equity_nvda_price", "ev_crypto_btc_price", "ev_calendar_0", "ev_sector_information_technology"):
        assert facts.evidence_index[key].updated_at is None, key


# -------------------------------------------------------------------------------------
# #125: full-run-path fact-layer verdict reason (the never-tested risk/fact write path)
# -------------------------------------------------------------------------------------


def _full_run_results(**overrides: Any) -> dict[str, Any]:
    """A `results` dict for `_run_risk_and_write` built entirely from factories.

    Every dataset is a valid synthetic envelope; the degraded flag that matters (#125) is
    `news_degraded`, which the caller flips. This mirrors what a real `--full` run feeds in
    after collection (payloads + per-domain collector meta).
    """
    meta = {
        "provider": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
        "degraded": False,
        "data_quality": 1.0,
    }
    results = {
        "macro": make_envelope("macro")["payload"],
        "equities": make_envelope("equities")["payload"],
        "sectors": make_envelope("sectors")["payload"],
        "crypto": make_envelope("crypto")["payload"],
        "commodities": make_envelope("commodities")["payload"],
        "news": make_envelope("news")["payload"],
        "calendar": make_envelope("calendar")["payload"],
        "market_meta": dict(meta, provider=dict(meta["provider"], provider="yfinance")),
        "macro_meta": dict(meta, provider=dict(meta["provider"], provider="fred")),
        "news_meta": dict(meta, provider=dict(meta["provider"], provider="rss_news")),
        "calendar_meta": dict(meta, provider=dict(meta["provider"], provider="fmp")),
        "news_degraded": False,
        "calendar_degraded": False,
        "provider_status": {},
        "histories": {},
        "series_history": {},
        "qualities": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    }
    results.update(overrides)
    return results


def _full_run_dataset(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, record_key: str, **overrides: Any
) -> dict[str, Any]:
    """Drive the real `_run_risk_and_write` against a tmp data dir and return the published
    freshness record for `record_key`. Closes the #99 blind spot: the full risk/fact write path
    is what actually broke `--full` on 08-07 morning."""
    import pipeline.run as run_module
    from pipeline.storage.writer import StorageWriter

    writer = StorageWriter(data_dir)
    monkeypatch.setattr(
        run_module, "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=data_dir / "artifacts"),
    )
    ok, error = run_module._run_risk_and_write(_full_run_results(**overrides), writer, "test-full")
    assert ok, f"full-path write failed: {error}"
    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    return freshness["datasets"][record_key]


def _full_run_factlayer(data_dir: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> dict[str, Any]:
    """The published `factlayer` freshness record from a real `_run_risk_and_write`."""
    return _full_run_dataset(data_dir, monkeypatch, "factlayer", **overrides)


def _full_run_dashboard(data_dir: Path, monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> dict[str, Any]:
    """The published `dashboard` freshness record from a real `_run_risk_and_write`."""
    return _full_run_dataset(data_dir, monkeypatch, "dashboard", **overrides)


def test_full_path_factlayer_reason_names_degraded_news_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#125: when news (an input) is degraded, the fact-layer reason is `input_dataset_unhealthy`
    naming the culprit — not the input's own `provider_http_error`, which would falsely imply
    the fact layer itself hit a provider error. This is exactly the 17:14Z production state:
    news provider_http_error → factlayer must say input_dataset_unhealthy, not the same code.
    """
    record = _full_run_factlayer(
        tmp_path / "data", monkeypatch,
        news_degraded=True,
        news_meta={
            "provider": {"provider": "rss_news", "used_fallback": False, "from_cache": False},
            "degraded": True,
            "data_quality": 1.0,
        },
    )
    assert record["status"] == "degraded"
    assert record["reason"]["code"] == "input_dataset_unhealthy"
    assert "news" in record["reason"]["detail"]


def test_full_path_factlayer_healthy_reason_when_inputs_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#125 control: with no degraded input, the fact-layer verdict never fabricates
    `input_dataset_unhealthy` (the factories' generated_at predates the wall clock by days,
    so the time ladder yields `stale`/`interval_exceeded` — deterministic and fine)."""
    record = _full_run_factlayer(tmp_path / "data", monkeypatch)
    assert record["status"] != "degraded"
    assert record["reason"]["code"] != "input_dataset_unhealthy"


def test_full_path_dashboard_reason_names_degraded_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#174: the dashboard never contacts a provider, so a degraded dashboard must say
    `input_dataset_unhealthy` naming its degraded inputs — not the default
    `provider_http_error`, which would falsely imply the dashboard itself hit a provider.
    Aggregation mirrors the fact-layer pattern: culprits = the inputs at the worst status."""
    record = _full_run_dashboard(
        tmp_path / "data", monkeypatch,
        market_meta={
            "provider": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
            "data_quality": 1.0,
            "degraded": ["equity unavailable"],
            "degraded_by_dataset": {
                "equities": True,
                "crypto": False,
                "commodities": False,
                "sectors": False,
            },
            "data_quality_by_dataset": {
                "equities": 0.8,
                "crypto": 1.0,
                "commodities": 1.0,
                "sectors": 1.0,
            },
            "source_updated_at_by_dataset": {
                "equities": None,
                "crypto": None,
                "commodities": None,
                "sectors": None,
            },
        },
    )
    assert record["status"] == "degraded"
    assert record["reason"]["code"] == "input_dataset_unhealthy"
    assert "equities" in record["reason"]["detail"], record["reason"]["detail"]
    assert "risk" in record["reason"]["detail"], record["reason"]["detail"]


def test_full_path_dashboard_healthy_reason_when_inputs_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#174 control: with healthy inputs the dashboard verdict never fabricates
    `input_dataset_unhealthy` (the dashboard's own generated_at is the run clock, so the
    time ladder yields `fresh`/`ok` — deterministic and fine)."""
    record = _full_run_dashboard(tmp_path / "data", monkeypatch)
    assert record["status"] != "degraded"
    assert record["reason"]["code"] != "input_dataset_unhealthy"


def test_full_path_sectors_reason_detail_names_failed_theme_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#174: the sectors Status-page reason keeps `provider_http_error` but now carries the
    detail naming the failed theme series the collector exposed — the delisted-symbol
    diagnosis is visible instead of only living in sources.json telemetry."""
    record = _full_run_dataset(
        tmp_path / "data", monkeypatch, "sectors",
        market_meta={
            "provider": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
            "data_quality": 1.0,
            "degraded": ["ROK: history unavailable"],
            "degraded_by_dataset": {
                "equities": False,
                "crypto": False,
                "commodities": False,
                "sectors": True,
            },
            "data_quality_by_dataset": {
                "equities": 1.0,
                "crypto": 1.0,
                "commodities": 1.0,
                "sectors": 0.8,
            },
            "source_updated_at_by_dataset": {
                "equities": None,
                "crypto": None,
                "commodities": None,
                "sectors": None,
            },
            "degraded_detail_by_dataset": {
                "sectors": "theme series unavailable: hist_ROK_1y",
            },
        },
    )
    assert record["status"] == "degraded"
    assert record["reason"]["code"] == "provider_http_error"
    assert record["reason"]["detail"] == "theme series unavailable: hist_ROK_1y"


def test_dashboard_inherits_degradation_from_commodity_risk_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commodity failure degrades risk and therefore the dashboard that renders it."""
    import pipeline.run as run_module
    from pipeline.storage.writer import StorageWriter

    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=tmp_path / "artifacts"),
    )
    results = _full_run_results(
        market_meta={
            "provider": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
            "data_quality": 1.0,
            "degraded": ["commodity unavailable"],
            "degraded_by_dataset": {
                "equities": False,
                "crypto": False,
                "commodities": True,
                "sectors": False,
            },
            "data_quality_by_dataset": {
                "equities": 1.0,
                "crypto": 1.0,
                "commodities": 0.8,
                "sectors": 1.0,
            },
            "source_updated_at_by_dataset": {
                "equities": None,
                "crypto": None,
                "commodities": None,
                "sectors": None,
            },
        }
    )
    ok, error = run_module._run_risk_and_write(results, StorageWriter(data_dir), "test-full")
    assert ok, error

    freshness = json.loads((data_dir / "metadata" / "freshness.json").read_text(encoding="utf-8"))
    assert freshness["datasets"]["risk"]["status"] == "degraded"
    assert freshness["datasets"]["dashboard"]["status"] == "degraded"


def test_full_path_rejects_canonical_validation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production-like write path must honor the composed Python validator result."""
    import pipeline.run as run_module
    from pipeline.storage.writer import StorageWriter
    from pipeline.validation.ci_checks import CheckReport

    data_dir = tmp_path / "data"
    writer = StorageWriter(data_dir)
    monkeypatch.setattr(
        run_module,
        "settings",
        Settings(_env_file=None, data_dir=data_dir, artifacts_dir=data_dir / "artifacts"),
    )
    monkeypatch.setattr(
        run_module,
        "run_data_validation",
        lambda _data_dir: CheckReport(errors=["forced canonical validation failure"]),
    )

    ok, error = run_module._run_risk_and_write(_full_run_results(), writer, "test-full")

    assert not ok
    assert error == "validation failed: forced canonical validation failure"
