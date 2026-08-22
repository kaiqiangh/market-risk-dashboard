#!/usr/bin/env python
"""Regenerate tests/pipeline/golden/run_manifest.json (#192).

Run ONLY against the pre-refactor reference state (or after a deliberate,
ticket-referenced behavior change): the whole point of the manifest is that a
plain refactor must not be able to refresh it silently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.pipeline.golden_support import FROZEN_TS, manifest, publish  # noqa: E402


def main() -> int:
    import tempfile

    from pipeline.storage import StorageWriter

    root = Path(tempfile.mkdtemp()) / "data"
    publish(StorageWriter(root), FROZEN_TS)
    out = Path(__file__).resolve().parents[1] / "tests/pipeline/golden/run_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    recorded = manifest(root)
    out.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"recorded {len(recorded)} files -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
