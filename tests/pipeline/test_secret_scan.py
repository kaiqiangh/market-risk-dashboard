"""Publish secret scanner coverage contract tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_SCRIPT = REPO_ROOT / "scripts" / "scan-secrets.mjs"


def test_secret_scan_fails_closed_for_an_oversized_tracked_file(tmp_path: Path) -> None:
    """An unscanned tracked file is a failed gate, not a clean result."""
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "oversized.bin").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    subprocess.run(["git", "add", "oversized.bin"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["node", str(SCAN_SCRIPT), "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "scan coverage incomplete" in result.stdout
