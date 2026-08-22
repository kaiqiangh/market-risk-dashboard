"""Byte-identical golden lock for the run.py write path (#192).

T6 restructures pipeline/run.py; the acceptance bar is ZERO behavior change. This
test drives _finalize_and_write + _build_dashboard over synthetic factory payloads
(frozen generated_at) and asserts a SHA256 manifest of every file StorageWriter
published - any accidental semantic drift breaks it. The manifest was recorded
against the PRE-refactor tree; regenerate only via scripts/record_golden.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.pipeline.golden_support import FROZEN_TS, publish
from tests.pipeline.golden_support import manifest as build_manifest

GOLDEN = Path(__file__).parent / "golden" / "run_manifest.json"


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    from pipeline.storage import StorageWriter

    root = tmp_path / "data"
    publish(StorageWriter(root), FROZEN_TS)
    return root


def test_run_write_path_manifest_is_stable(data_root: Path) -> None:
    if not GOLDEN.exists():
        pytest.fail("golden manifest missing; run python scripts/record_golden.py")
    actual = build_manifest(data_root)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert actual == expected, (
        "published bytes drifted (#192): "
        f"missing={sorted(set(expected) - set(actual))} "
        f"extra={sorted(set(actual) - set(expected))} "
        f"changed={sorted(k for k in set(actual) & set(expected) if actual[k] != expected[k])}"
    )
