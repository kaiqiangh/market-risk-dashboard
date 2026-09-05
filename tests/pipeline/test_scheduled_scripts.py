"""Executable contracts for the fail-closed validation and scheduled runner.

These tests use small fake executables so repository-state failures can be exercised
without touching the checkout or requiring a real remote. The published-data validation
tests still run the real Node companion against the checked-in fixtures.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_data.sh"
SCHEDULED_SCRIPT = REPO_ROOT / "scripts" / "run_scheduled.sh"


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _scheduler_harness(tmp_path: Path, *, fake_stat: bool = False) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "commands.log"
    original_path = os.environ.get("PATH", "")

    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -u
printf '%s\\n' "$*" >> "$FAKE_GIT_LOG"
case "${1:-}" in
  pull) exit "${FAKE_GIT_PULL:-0}" ;;
  status)
    # porcelain stub (#190): "dirty" emits an untracked-style entry, clean prints nothing.
    if [[ "${FAKE_GIT_STATUS:-clean}" != "clean" ]]; then
      printf ' M public/data/latest/market.json\n'
    fi
    exit 0
    ;;
  diff)
    if [[ "${FAKE_GIT_DIFF:-clean}" == "clean" ]]; then exit 0; else exit 1; fi
    ;;
  add) exit 0 ;;
  commit) exit "${FAKE_GIT_COMMIT:-0}" ;;
  rev-parse) echo "abc123"; exit 0 ;;
  show) exit 0 ;;
  push) exit "${FAKE_GIT_PUSH:-0}" ;;
  ls-remote) echo "${FAKE_GIT_REMOTE:-abc123} refs/heads/dev"; exit 0 ;;
esac
exit 0
""",
    )
    python_bin = _write_executable(
        bin_dir / "fake-python",
        """#!/usr/bin/env bash
printf 'python %s\\n' "$*" >> "$FAKE_GIT_LOG"
if [[ "${1:-}" == "-c" ]]; then exit "${FAKE_IMPORT_STATUS:-0}"; fi
exit "${FAKE_PYTHON_STATUS:-0}"
""",
    )
    validation = _write_executable(
        bin_dir / "fake-validation",
        """#!/usr/bin/env bash
printf 'validation %s\\n' "$*" >> "$FAKE_GIT_LOG"
[[ "${1:-}" == "--scheduled" ]] || exit 98
exit "${FAKE_VALIDATE_STATUS:-0}"
""",
    )
    if fake_stat:
        _write_executable(
            bin_dir / "stat",
            """#!/usr/bin/env bash
case "${FAKE_STAT_PROFILE:-gnu}:${1:-} ${2:-}" in
  gnu:"-f %m") printf 'File: fake filesystem stats\\n'; exit 0 ;;
  gnu:"-c %Y") printf '%s\\n' "${FAKE_STAT_MTIME:-0}"; exit 0 ;;
  bsd:"-c %Y") printf 'File: fake filesystem stats\\n'; exit 0 ;;
  bsd:"-f %m") printf '%s\\n' "${FAKE_STAT_MTIME:-0}"; exit 0 ;;
esac
exit 1
""",
        )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{original_path}",
        "FAKE_GIT_LOG": str(log),
        "SCHEDULED_PYTHON": str(python_bin),
        "VALIDATE_DATA_SCRIPT": str(validation),
    }
    return env, log


def _run_scheduled(
    tmp_path: Path, *, fake_stat: bool = False, **overrides: str
) -> tuple[subprocess.CompletedProcess[str], str]:
    env, log = _scheduler_harness(tmp_path, fake_stat=fake_stat)
    env.update(overrides)
    result = subprocess.run(
        ["bash", str(SCHEDULED_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


def test_pull_failure_stops_before_collection(tmp_path: Path) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_PULL="1")

    assert result.returncode == 20
    assert "collection did not start" in result.stderr
    assert "python -m pipeline.run" not in log


def test_no_change_is_success_without_commit_or_push(tmp_path: Path) -> None:
    # Default stubs report a clean porcelain status - nothing meaningful changed.
    result, log = _run_scheduled(tmp_path)

    assert result.returncode == 0
    assert "no meaningful changes" in result.stdout
    assert "commit" not in log
    assert "push" not in log


def test_commit_failure_is_fatal_and_does_not_push(tmp_path: Path) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty", FAKE_GIT_COMMIT="1")

    assert result.returncode == 23
    assert "nothing was pushed" in result.stderr
    assert "commit" in log
    assert "push" not in log


def test_push_failure_keeps_verified_local_commit_for_retry(tmp_path: Path) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty", FAKE_GIT_PUSH="1")

    assert result.returncode == 24
    assert "abc123" in result.stderr
    assert "push" in log
    assert "ls-remote" not in log


def test_remote_mismatch_is_fatal_after_push(tmp_path: Path) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty", FAKE_GIT_REMOTE="different")

    assert result.returncode == 24
    assert "remote verification failed" in result.stderr
    assert "abc123" in result.stderr
    assert "ls-remote" in log


def test_success_verifies_remote_commit(tmp_path: Path) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty")

    assert result.returncode == 0
    assert "published commit abc123" in result.stdout
    assert "ls-remote" in log


@pytest.mark.parametrize(
    ("env_name", "env_value", "expected"),
    [
        ("FAKE_VALIDATE_STATUS", "10", 10),
        ("FAKE_VALIDATE_STATUS", "11", 22),
        ("FAKE_IMPORT_STATUS", "1", 10),
        ("FAKE_PYTHON_STATUS", "1", 21),
    ],
)
def test_scheduled_failure_classes_have_stable_exit_codes(
    tmp_path: Path, env_name: str, env_value: str, expected: int
) -> None:
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty", **{env_name: env_value})

    assert result.returncode == expected
    if env_name == "FAKE_VALIDATE_STATUS":
        assert "commit" not in log
        assert "push" not in log


def _validation_env(tmp_path: Path, *, include_node: bool = True) -> dict[str, str]:
    fake_python = _write_executable(
        tmp_path / "fake-python",
        """#!/usr/bin/env bash
if [[ "${1:-}" == "-c" ]]; then exit 1; fi
exit 0
""",
    )
    env = {**os.environ, "VALIDATE_DATA_PYTHON": str(fake_python)}
    if not include_node:
        env["PATH"] = str(tmp_path)
    return env


def test_validation_requires_full_python_dependencies_by_default(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required to exercise the mandatory secret gate")

    result = subprocess.run(
        ["/bin/bash", str(VALIDATE_SCRIPT)],
        cwd=REPO_ROOT,
        env=_validation_env(tmp_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 10
    assert "full Python validation dependencies unavailable" in result.stderr
    assert "reduced-diagnostic" not in result.stderr


def test_reduced_validation_is_explicit_and_marked(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node is required to exercise reduced diagnostics")

    result = subprocess.run(
        ["/bin/bash", str(VALIDATE_SCRIPT), "--diagnostic-reduced"],
        cwd=REPO_ROOT,
        env=_validation_env(tmp_path),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "mode=reduced-diagnostic" in result.stderr
    assert "passed in reduced-diagnostic mode" in result.stderr


def test_reduced_validation_is_rejected_for_scheduled_runs(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(VALIDATE_SCRIPT), "--scheduled", "--diagnostic-reduced"],
        cwd=REPO_ROOT,
        env=_validation_env(tmp_path, include_node=False),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 10
    assert "not allowed for scheduled/production" in result.stderr


def test_missing_node_fails_mandatory_secret_scan(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(VALIDATE_SCRIPT)],
        cwd=REPO_ROOT,
        env=_validation_env(tmp_path, include_node=False),
        text=True,
        capture_output=True,
    )

    assert result.returncode == 10
    assert "mandatory secret scan cannot run" in result.stderr


# ---- #190: porcelain change detection, single-instance lock, branch parameterization ----


def test_new_untracked_file_triggers_commit_even_when_diff_is_clean(tmp_path: Path) -> None:
    """The #190 bug: git diff --quiet missed NEW untracked files, so a brand-new dataset
    was silently never committed. Porcelain status must be the decision driver."""
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty", FAKE_GIT_DIFF="clean")

    assert result.returncode == 0
    assert "commit" in log
    assert "push" in log
    assert "no meaningful changes" not in result.stdout


@pytest.mark.parametrize("stat_profile", ["gnu", "bsd"])
def test_lock_conflict_exits_25_without_running_pipeline(tmp_path: Path, stat_profile: str) -> None:
    """A concurrent instance (fresh lock) must stop the run before any collection."""
    lock_dir = tmp_path / "sched.lock"
    lock_dir.mkdir()
    import time

    # Force the mkdir mechanism (#190 review): flock exists on Linux CI, and the
    # conflict semantics differ between mechanisms - this test pins the portable path.
    result, log = _run_scheduled(
        tmp_path,
        fake_stat=True,
        FAKE_STAT_PROFILE=stat_profile,
        FAKE_STAT_MTIME=str(int(time.time())),
        SCHEDULED_LOCK_DIR=str(lock_dir),
        SCHEDULED_LOCK_MODE="mkdir",
    )

    assert result.returncode == 25
    assert "python -m pipeline.run" not in log
    assert lock_dir.exists(), "a loser must never remove the winner's lock"


@pytest.mark.parametrize("stat_profile", ["gnu", "bsd"])
def test_stale_lock_is_reclaimed_and_run_proceeds(tmp_path: Path, stat_profile: str) -> None:
    """A crashed run's leftover lock older than the stale window must not wedge the
    scheduler forever."""
    import time

    lock_dir = tmp_path / "sched.lock"
    lock_dir.mkdir()
    old = time.time() - 9000  # default stale window is 7200s
    os.utime(lock_dir, (old, old))
    result, log = _run_scheduled(
        tmp_path,
        fake_stat=True,
        FAKE_STAT_PROFILE=stat_profile,
        SCHEDULED_LOCK_DIR=str(lock_dir),
        SCHEDULED_LOCK_MODE="mkdir",
        FAKE_GIT_STATUS="dirty",
    )

    assert result.returncode == 0
    assert "removing stale lock" in result.stderr
    assert "commit" in log


def test_branch_override_cannot_escape_dev(tmp_path: Path) -> None:
    """The scheduler must ignore branch overrides and publish only to dev."""
    result, log = _run_scheduled(
        tmp_path, SCHEDULED_BRANCH="main", FAKE_GIT_STATUS="dirty", FAKE_GIT_REMOTE="abc123"
    )

    assert result.returncode == 0
    assert "--rebase origin dev" in log
    assert "push origin dev" in log
    assert "main" not in log


def test_timeout_wrapper_wraps_network_steps(tmp_path: Path) -> None:
    """Network steps still reach git with expected args under the timeout wrapper."""
    result, log = _run_scheduled(tmp_path, FAKE_GIT_STATUS="dirty")

    assert result.returncode == 0
    assert "--rebase origin dev" in log
    assert "push origin dev" in log
    assert "ls-remote origin refs/heads/dev" in log
