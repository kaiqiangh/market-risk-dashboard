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
