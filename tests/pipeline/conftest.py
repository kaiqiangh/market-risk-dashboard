"""Shared fixtures for the pipeline test suite.

Two responsibilities:

1. Hand every test a synthetic dataset tree built by :mod:`tests.pipeline.factories`, so no test
   depends on what the last pipeline run left on disk.
2. Enforce that. An audit hook records every attempt to open a file inside the published data
   directory. ``test_suite_does_not_read_published_data`` asserts the record is empty, giving a
   named failure with a useful message; a session hook independently fails the run, which covers
   reads that happen after that test and runs where the test was not selected.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from tests.pipeline.factories import DEFAULT_NOW, build_data_dir

# The directory the suite must not touch: <repo>/public/data.
PUBLISHED_DATA_DIR: Path = Path(__file__).resolve().parents[2] / "public" / "data"
_PUBLISHED_PREFIX: str = str(PUBLISHED_DATA_DIR) + os.sep

# Absolute paths of every open() attempt inside PUBLISHED_DATA_DIR, in order.
_published_reads: list[str] = []


def _audit_open(event: str, args: tuple[Any, ...]) -> None:
    """Audit hook: record opens under the published data directory.

    Must never raise — an exception here would propagate into the audited operation and break
    unrelated code. Everything is defensive on purpose.
    """
    if event != "open" or not args:
        return
    try:
        target = args[0]
        if isinstance(target, int):  # already-open file descriptor, not a path
            return
        resolved = os.path.abspath(os.fspath(target))
        if resolved == str(PUBLISHED_DATA_DIR) or resolved.startswith(_PUBLISHED_PREFIX):
            _published_reads.append(resolved)
    except Exception:  # noqa: BLE001 — an audit hook must not disturb the audited call
        return


sys.addaudithook(_audit_open)


@pytest.fixture()
def now() -> datetime:
    """The frozen instant every synthetic document is generated at.

    Freshness outcomes are then a property of the fixture, not of the wall clock.
    """
    return DEFAULT_NOW


@pytest.fixture()
def synthetic_data_dir(tmp_path: Path) -> Path:
    """A complete, valid ``public/data``-shaped tree under ``tmp_path``.

    Validating it produces zero errors and zero warnings, so a test can overwrite exactly one
    file and attribute every resulting diagnostic to that change.
    """
    return build_data_dir(tmp_path / "data")


@pytest.fixture()
def synthetic_latest_dir(synthetic_data_dir: Path) -> Path:
    """The ``latest/`` directory of :func:`synthetic_data_dir`."""
    return synthetic_data_dir / "latest"


@pytest.fixture()
def make_data_dir(tmp_path: Path) -> Callable[..., Path]:
    """Build additional synthetic trees with per-file overrides.

    Each call gets its own directory, so a test may compare several variants::

        degraded = make_data_dir(latest={"analysis.zh-CN.json": REMOVE, "analysis.en.json": REMOVE})
    """
    counter = {"n": 0}

    def _make(**kwargs: Any) -> Path:
        counter["n"] += 1
        return build_data_dir(tmp_path / f"data-{counter['n']}", **kwargs)

    return _make


@pytest.fixture()
def empty_data_dir(tmp_path: Path) -> Path:
    """A data directory whose ``latest/`` exists but is empty (nothing published yet)."""
    root = tmp_path / "empty-data"
    (root / "latest").mkdir(parents=True)
    return root


@pytest.fixture()
def published_data_reads() -> list[str]:
    """Every published-data file opened so far in this session (should always be empty)."""
    return list(_published_reads)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the session if anything opened the published data directory.

    ``test_suite_does_not_read_published_data`` only sees reads that happened before it, and it
    may not be selected at all. This closes both windows, so the invariant holds for whatever
    subset of the suite actually ran.
    """
    if _published_reads and exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    """Explain a published-data guard failure, which is otherwise invisible in the report."""
    if not _published_reads:
        return
    terminalreporter.section("published data guard", red=True, bold=True)
    terminalreporter.write_line(
        f"FAILED: {len(_published_reads)} read(s) of the published data directory during this run. "
        "Tests must build their own data via tests/pipeline/factories.py — published artifacts "
        "cannot be regenerated without API keys and cannot be made to fail on demand."
    )
    for path in dict.fromkeys(_published_reads):
        terminalreporter.write_line(f"  {path}")
