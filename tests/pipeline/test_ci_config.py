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

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

_YAML_KEY = re.compile(r"^\s*([a-zA-Z0-9_-]+)\s*:", re.MULTILINE)
#: The F821 gate must be a real workflow step (`run: ruff check . --select F821`), not
#: merely quoted in a comment — the comment at the top of test-pipeline.yml contains the
#: exact command text, so a substring match stays green even if the gate line is deleted.
_F821_RUN_LINE = re.compile(r"^\s*run:\s*ruff check \.\s*--select F821", re.MULTILINE)
#: Hand-written tables that #101 replaced with the generated registry. Their reappearance
#: in validate-json.mjs is the regression, so these patterns now assert absence.
_ENVELOPE_FILES_SET = re.compile(r"ENVELOPE_FILES\s*=\s*new Set\(\[(.*?)\]\)", re.DOTALL)
_FRESHNESS_SET = re.compile(r"FRESHNESS\s*=\s*new Set\(\s*\[", re.DOTALL)
_ACTION_REF = re.compile(
    r"^\s*(?:-\s+)?uses:\s+([^\s#]+)@([^\s#]+)",
    re.MULTILINE,
)


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


def test_test_pipeline_runs_full_data_validation_and_node_companion() -> None:
    """Every CI run must enforce the full validator; Node is only the companion check."""
    text = _read_workflow("test-pipeline.yml")

    assert "scripts/validate_data.sh --scheduled --data-dir public/data" in text
    assert "node scripts/validate-json.mjs --data-dir public/data" in text


def _generated_constants() -> dict:
    """The contract constants the Node gate reads (src/schemas/generated/constants.json)."""
    path = REPO_ROOT / "src" / "schemas" / "generated" / "constants.json"
    assert path.exists(), f"missing generated contract constants: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_f821_is_the_fatal_lint_gate() -> None:
    """F821 (undefined name) fails the build; everything else is advisory.

    Ruling (#60, board item 5): F821 pinned fatal, never a numeric threshold. The ruff
    invocation in CI must select F821 so no warning-count ratchet can be gamed. The
    check anchors on the workflow `run:` line — a comment quoting the command must not
    satisfy it (QA mutation: deleting the run line while keeping the comment stayed
    green under the substring check).
    """
    text = _read_workflow("test-pipeline.yml")

    assert "ruff" in text, "the Python job must run ruff"
    assert _F821_RUN_LINE.search(text), (
        "the F821 gate must be a real run step: `run: ruff check . --select F821`"
    )


def test_validate_json_mjs_is_aligned_with_the_schema_homes() -> None:
    """#74/#101: the Node gate covers every enveloped dataset and keeps no private copy.

    #74's finding was that `validate-json.mjs` skipped dashboard.json while the Python gate
    validated it. The fix then was a hand-written `ENVELOPE_FILES = new Set([...])` literal
    plus a hand-written FRESHNESS copy, and this test pinned their contents — which only
    ever caught the drift after someone had already shipped it.

    #101 removed the literals: the gate now reads src/schemas/generated/constants.json,
    generated from pipeline/schemas/registry.py. Divergence is no longer a thing to detect,
    so the test moves up a level and pins the mechanism instead — the gate must read the
    generated registry, must not reintroduce a private table, and the registry must still
    say dashboard is an envelope.
    """
    text = (REPO_ROOT / "scripts" / "validate-json.mjs").read_text(encoding="utf-8")

    assert "generated" in text and "constants.json" in text, (
        "validate-json.mjs must read src/schemas/generated/constants.json, "
        "not maintain its own dataset table"
    )
    assert not _ENVELOPE_FILES_SET.search(text), (
        "validate-json.mjs must not reintroduce a hand-written ENVELOPE_FILES literal — "
        "the enveloped/standalone split comes from the generated registry (#101)"
    )
    assert not _FRESHNESS_SET.search(text), (
        "validate-json.mjs must not reintroduce a hand-written freshness vocabulary — "
        "it comes from constants.json:freshness_status (#101)"
    )

    constants = _generated_constants()
    dashboard = constants["datasets"].get("dashboard")
    assert dashboard, "dashboard must be a registered dataset (#74: the Node gate skipped it)"
    assert dashboard["enveloped"] is True, "dashboard.json is an envelope and must be gated as one"
    assert "dashboard.json" in dashboard["filenames"]

    # The gate resolves files through the registry, so every enveloped dataset is covered by
    # construction. Assert the registry actually knows the full set rather than a subset.
    enveloped = {k for k, spec in constants["datasets"].items() if spec["enveloped"]}
    assert {"macro", "equities", "sectors", "crypto", "news", "calendar", "risk", "dashboard"} <= enveloped


def test_validate_json_mjs_cross_checks_degraded_agreement() -> None:
    """#89/#101: the two metadata files are projections of one record, so the Node gate must
    assert they agree on `degraded` per domain — the contradiction the record was written to
    make impossible (calendar `fresh` in one file, `degraded` in the other)."""
    text = (REPO_ROOT / "scripts" / "validate-json.mjs").read_text(encoding="utf-8")

    assert 'new Set(["degraded", "missing", "stale"])' in text, (
        "validate-json.mjs must mirror outcomes.py's unhealthy set for the degraded-agreement check"
    )
    assert "disagrees with freshness.json" in text, (
        "validate-json.mjs must error when a domain's degraded disagrees with freshness.json"
    )


def test_validate_data_runs_contract_drift_gate() -> None:
    """#101 criterion 2: `check:contracts` must run in CI, and codegen changes must trigger it.

    A generated-contract drift that only `npm run check:contracts` locally would catch is the
    same class of silent gap #74 closed for the Python suite: the gate exists, but if no
    workflow runs it, drift ships.
    """
    text = _read_workflow("validate-data.yml")

    assert "npm run check:contracts" in text, (
        "validate-data.yml must run the contract drift gate (`npm run check:contracts`)"
    )
    assert '"scripts/gen_ts_contracts.py"' in text, (
        "validate-data.yml paths: must watch scripts/gen_ts_contracts.py so a codegen change triggers the gate"
    )
    assert '"src/schemas/generated/**"' in text, (
        "validate-data.yml paths: must watch src/schemas/generated/** so a drift PR triggers the gate"
    )


def test_workflow_files_are_valid_yaml() -> None:
    """CI workflows must parse as YAML — an unparseable gate silently never runs.

    Regression: the "Contract drift gate (#101): …" step name contained `#101`, which YAML
    treats as a comment, so validate-data.yml failed to parse and the gate was red-without-
    running on every PR until someone read the Actions page. A step name containing `:` or
    `#` must be quoted.
    """
    import yaml

    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        yaml.safe_load(path.read_text(encoding="utf-8"))


def test_secret_gate_is_wired_into_local_and_ci_validation() -> None:
    """S-1/#92: the publish secret gate must run in both the local script and CI."""
    workflow = _read_workflow("validate-data.yml")
    assert "scan-secrets.mjs" in workflow, (
        "validate-data.yml must run the secret scan before publish"
    )
    script = (REPO_ROOT / "scripts" / "validate_data.sh").read_text(encoding="utf-8")
    assert "scan-secrets.mjs" in script, (
        "validate_data.sh must run the secret scan before the data checks"
    )


def test_local_validation_fails_closed_and_marks_reduced_diagnostics() -> None:
    """The local/scheduled validator must not silently downgrade its confidence."""
    script = (REPO_ROOT / "scripts" / "validate_data.sh").read_text(encoding="utf-8")

    assert "pipeline.validation.ci_checks" in script
    assert "--diagnostic-reduced" in script
    assert "mode=reduced-diagnostic" in script
    assert "VALIDATE_DATA_PRODUCTION" in script
    assert "mandatory secret scan cannot run" in script
    assert "falling back to Node" not in script
    assert "npm run check:contracts" in script


def test_scheduled_runner_fails_closed_after_repository_errors() -> None:
    """Pull, commit, push, and remote verification must all be observable failures."""
    script = (REPO_ROOT / "scripts" / "run_scheduled.sh").read_text(encoding="utf-8")

    assert "collection did not start" in script
    assert "continuing with local state" not in script
    assert "nothing was pushed" in script
    assert "local verified commit $COMMIT_SHA" in script
    assert "git rev-parse HEAD" in script
    # Branch is parameterized (#190): default dev via SCHEDULED_BRANCH, but never
    # hardcoded, so a scheduled run can target another branch without edits.
    assert 'BRANCH="${SCHEDULED_BRANCH:-dev}"' in script
    assert "git ls-remote origin \"refs/heads/$BRANCH\"" in script
    assert "|| true" not in script
    assert "git pull --rebase origin \"$BRANCH\"; then" in script
    # Timeouts wrap every network/bulk step (#190).
    assert "run_with_timeout 120 git pull" in script
    assert "run_with_timeout 300 git push" in script
    assert "run_with_timeout 30 git ls-remote" in script
    # Validation is a bulk step too (#190 review): it must be time-bounded like the rest.
    assert "SCHEDULED_TIMEOUT_VALIDATE:-1800" in script
    assert "run_with_timeout \"${SCHEDULED_TIMEOUT_VALIDATE:-1800}\" \"$VALIDATE_SCRIPT\" --scheduled" in script
    assert "git status --porcelain -- public/ config/" in script


def test_deploy_pages_runs_full_data_and_secret_gates() -> None:
    """Artifact upload must be downstream of Python validation and secret scanning."""
    workflow = _read_workflow("deploy-pages.yml")

    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert "python -m pipeline.validation.ci_checks --data-dir public/data" in workflow
    assert "scripts/scan-secrets.mjs --root ." in workflow
    assert "npm run check:contracts" in workflow
    assert "Validate JSON data (Node structural companion)" in workflow
    assert workflow.index("run: npm run build") < workflow.index("run: node scripts/scan-secrets.mjs --root .")
    assert workflow.index("run: node scripts/scan-secrets.mjs --root .") < workflow.index(
        "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa"
    )


def test_theme_health_gate_is_scheduled_read_only_and_runs_symbol_health() -> None:
    """#175: a dead theme symbol must surface within a day — daily schedule + manual dispatch.

    The workflow must be triggerable on a schedule and on demand, run with minimal
    read-only permissions (Architecture §8.14 — no secrets, no issue creation), and
    actually invoke the symbol_health CLI against the committed data tree.
    """
    text = _read_workflow("theme-health.yml")

    assert _has_yaml_key(text, "schedule"), "theme-health.yml must run on a daily schedule"
    assert re.search(r"^\s*-\s*cron:", text, re.MULTILINE), (
        "the schedule must be a real cron entry (line-anchored, not a prose mention)"
    )
    assert _has_yaml_key(text, "workflow_dispatch"), (
        "theme-health.yml must be manually dispatchable for on-demand checks"
    )
    assert re.search(r"^\s*contents:\s*read\s*$", text, re.MULTILINE), (
        "the gate must be read-only: permissions.contents: read (Architecture §8.14)"
    )
    assert "python -m pipeline.validation.symbol_health --data-dir public/data" in text, (
        "theme-health.yml must run the symbol_health CLI against the committed data"
    )
    assert "constraints/py312.txt" in text, (
        "theme-health.yml must install pipeline dependencies through constraints/py312.txt"
    )


def test_ci_actions_are_pinned_to_full_commit_shas() -> None:
    """Every external action must resolve to an auditable immutable revision."""
    refs = [
        (path.name, action, ref)
        for path in sorted(WORKFLOWS_DIR.glob("*.yml"))
        for action, ref in _ACTION_REF.findall(path.read_text(encoding="utf-8"))
    ]

    assert refs, "workflow suite must contain action references"
    unpinned = [f"{name}: {action}@{ref}" for name, action, ref in refs if not re.fullmatch(r"[0-9a-f]{40}", ref)]
    assert not unpinned, "all external GitHub Actions must use full commit SHAs: " + ", ".join(unpinned)


def test_ci_uses_checked_in_python_constraints() -> None:
    """CI and release-path installs must share the checked-in Python resolution."""
    constraints = REPO_ROOT / "constraints" / "py312.txt"
    assert constraints.exists(), "the CI Python constraint file must be checked in"
    constraint_text = constraints.read_text(encoding="utf-8")
    assert "--python-version 3.12" in constraint_text
    assert "--python-platform x86_64-unknown-linux-gnu" in constraint_text
    for package in ("pydantic", "pydantic-settings", "pyyaml", "pytest", "ruff"):
        assert re.search(rf"^{re.escape(package)}==", constraint_text, re.MULTILINE), (
            f"constraints/py312.txt must pin {package}"
        )

    for workflow_name in ("test-pipeline.yml", "validate-data.yml", "deploy-pages.yml", "fallback-health.yml"):
        workflow = _read_workflow(workflow_name)
        assert "constraints/py312.txt" in workflow, (
            f"{workflow_name} must install Python dependencies through constraints/py312.txt"
        )


def test_frontend_ci_and_production_audit_gate_are_wired() -> None:
    """Frontend checks and the high production audit must run before release."""
    test_pipeline = _read_workflow("test-pipeline.yml")
    deploy_pages = _read_workflow("deploy-pages.yml")

    for workflow in (test_pipeline, deploy_pages):
        assert "npm ci" in workflow
        assert "npm audit --omit=dev --audit-level=high" in workflow
        for command in ("npm run lint", "npm run typecheck", "npm test", "npm run build"):
            assert command in workflow, f"missing frontend gate: {command}"

    assert "branches: [dev, main]" in deploy_pages, (
        "Pages publishing must run on push to dev and main (per-branch concurrency keeps them from cancelling each other)"
    )
    assert re.search(r"^\s*pages: write$", deploy_pages, re.MULTILINE), (
        "the deploy job must retain Pages write permission"
    )
    assert re.search(r"^\s*id-token: write$", deploy_pages, re.MULTILINE), (
        "the deploy job must retain OIDC permission"
    )


def test_pages_release_boundary_is_dev_and_main_and_fully_gated() -> None:
    """Dev and main may release Pages, but only after the full build gate; PRs never do.

    #172: the release boundary widened from main-only to dev+main, and the concurrency
    group became per-ref so a dev deploy can never cancel an in-flight main deploy (or
    vice versa). The deploy job still requires the complete build: Python validation,
    contract drift, audit, build and secret scan must all precede the artifact upload,
    and the production Pages environment stays unreachable from PR validation.
    """
    deploy_pages = _read_workflow("deploy-pages.yml")
    test_pipeline = _read_workflow("test-pipeline.yml")
    deploy_job = deploy_pages.split("\n  deploy:\n", maxsplit=1)[1]
    build_job = deploy_pages.split("\n  deploy:\n", maxsplit=1)[0]

    assert "pull_request" in test_pipeline
    assert "branches: [dev, main]" in test_pipeline
    assert "github-pages" not in test_pipeline
    assert "workflow_dispatch:" in deploy_pages
    assert "if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/dev'" in deploy_job, (
        "the deploy job must guard BOTH release refs (dev and main)"
    )
    assert "group: pages-${{ github.ref }}" in deploy_pages, (
        "the concurrency group must be per-ref so dev/main never cancel each other"
    )
    assert "cancel-in-progress: true" in deploy_pages
    assert "needs: build" in deploy_job
    assert "github-pages" in deploy_job
    assert "pages: write" not in build_job
    assert "id-token: write" not in build_job

    for command in (
        "python -m pipeline.validation.ci_checks --data-dir public/data",
        "npm run check:contracts",
        "npm audit --omit=dev --audit-level=high",
        "npm run build",
        "node scripts/scan-secrets.mjs --root .",
    ):
        assert command in build_job, f"release build is missing required gate: {command}"

    for gate in (
        "run: npm run build",
        "run: node scripts/scan-secrets.mjs --root .",
        "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa",
    ):
        assert gate in build_job
    assert build_job.index("run: npm run build") < build_job.index(
        "run: node scripts/scan-secrets.mjs --root ."
    ) < build_job.index("actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa")
