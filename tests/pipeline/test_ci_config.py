r"""CI configuration pins for #74.

CI YAML is not unit-testable end-to-end from a local checkout, but the contract #74
installs is: the data gate watches `pipeline/schemas/**`, the Python suite runs on
every PR without a path filter, and F821 is the one lint that fails the build. This
module pins those facts in the suite CI runs, so a drift in the workflow files is a
named failure rather than a silent gap.

Key-presence checks are line-anchored (`^\s*key\s*:`) rather than substring matches,
so a prose mention of a mechanism in a comment does not count as the mechanism being
used.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_YAML_KEY = re.compile(r"^\s*([a-zA-Z0-9_-]+)\s*:", re.MULTILINE)


def _read_workflow(name: str) -> str:
    path = WORKFLOWS_DIR / name
    assert path.exists(), f"missing workflow: {path}"
    return path.read_text(encoding="utf-8")


def _has_yaml_key(text: str, key: str) -> bool:
    return any(line_key == key for line_key in _YAML_KEY.findall(text))


def test_validate_data_watches_pipeline_schemas_with_no_bypass() -> None:
    """A schema-changing PR must trigger the data gate, and the red window must stay red.

    #74: `pipeline/schemas/**` in `validate-data.yml` `paths:` makes a PR that adds a
    required field turn CI red until the scheduled run regenerates `public/data`. That
    red is the system working, not a mistake, so the window is documented at the paths
    entry. No bypass (continue-on-error, label-gated skip, `if:` escape): a green gate
    during the window would be a lie.
    """
    text = _read_workflow("validate-data.yml")

    assert '"pipeline/schemas/**"' in text, "validate-data.yml must watch pipeline/schemas/**"
    assert "expected-red" in text, (
        "the paths entry must document the expected-red window (until the scheduled regeneration)"
    )
    assert not _has_yaml_key(text, "continue-on-error"), "no bypass: a red data gate must stay red"
    assert _has_yaml_key(text, "paths"), "validate-data.yml stays path-filtered (it is a data gate)"


def test_python_suite_runs_on_every_pull_request_and_push() -> None:
    """The Python job runs on PRs without a path filter, and on push to dev/main.

    A path filter on the Python job would be the exact defect #74 exists to fix — tests
    would not run when only `tests/` or `pipeline/` changed. So the workflow must not
    declare a `paths:` key at all.
    """
    text = _read_workflow("test-pipeline.yml")

    assert "pytest tests/pipeline/" in text, "the Python job must run the pipeline suite"
    assert "pull_request" in text, "the Python job must run on pull requests"
    assert "dev" in text and "main" in text, "the Python job must run on push to dev/main"
    assert not _has_yaml_key(text, "paths"), (
        "the Python job must NOT be path-filtered — a PR touching only tests/ must still run it"
    )


def test_f821_is_the_fatal_lint_gate() -> None:
    """F821 (undefined name) fails the build; everything else is advisory.

    Ruling (#60, board item 5): F821 pinned fatal, never a numeric threshold. The ruff
    invocation in CI must select F821 so no warning-count ratchet can be gamed.
    """
    text = _read_workflow("test-pipeline.yml")

    assert "ruff" in text, "the Python job must run ruff"
    assert "--select F821" in text, "F821 must be the fatal gate (ruff check . --select F821)"


def test_validate_json_mjs_is_aligned_with_the_schema_homes() -> None:
    """QA note (#74): the Node gate must not skip dashboard.json and must say where its enum lives.

    `validate-json.mjs` is deliberately zero-dependency, so it cannot import the Zod
    enum; instead it declares the canonical homes and must stay in sync. `dashboard.json`
    is an envelope (pipeline/schemas/dashboard.py, src/schemas/dashboard.ts) and is
    validated by the Python gate — the Node gate skipping it was a divergence.
    """
    text = (REPO_ROOT / "scripts" / "validate-json.mjs").read_text(encoding="utf-8")

    assert '"dashboard.json"' in text, "dashboard.json must be validated as an envelope, not skipped"
    assert "src/schemas/envelope.ts" in text, (
        "the FRESHNESS copy must document its canonical home (Zod enum)"
    )
