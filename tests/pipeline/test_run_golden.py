"""Byte-identical golden lock for the run.py write path (#192).

T6 restructures pipeline/run.py; the acceptance bar is ZERO behavior change. This
test drives _finalize_and_write + _build_dashboard over synthetic factory payloads
(frozen generated_at) and asserts a SHA256 manifest of every file StorageWriter
published - any accidental semantic drift breaks it. The manifest was recorded
against the PRE-refactor tree; regenerate only via scripts/record_golden.py.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.pipeline import factories

GOLDEN = Path(__file__).parent / "golden" / "run_manifest.json"
FROZEN_TS = "2026-08-22T12:00:00Z"


def _manifest(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _publish(writer, generated_at: str) -> None:
    """The write sequence main() performs for the full command, narrowed to datasets that
    cover every assembly branch: risk (derived inputs), market fallback provenance, news
    default provider, calendar detail, dashboard aggregation."""
    from pipeline.run import RunOutcomes, _build_dashboard, _finalize_and_write, _run_scope

    outcomes = RunOutcomes(scope=_run_scope("full"))

    risk_env = _finalize_and_write(
        writer, "risk", factories.make_risk_payload(), False, outcomes,
        provider="derived", data_quality=1.0, generated_at=generated_at,
    )
    equities = _finalize_and_write(
        writer, "equities", factories.make_equities_payload(), False, outcomes,
        provider="fmp", used_fallback=False, from_cache=False,
        data_quality=0.98, generated_at=generated_at,
        source_updated_at="2026-08-22T11:00:00Z",
    )
    crypto = _finalize_and_write(
        writer, "crypto", factories.make_crypto_payload(), True, outcomes,
        provider="binance", used_fallback=True, from_cache=False,
        data_quality=0.9, generated_at=generated_at, error_code="provider_http_5xx",
        detail="fallback exercised",
    )
    sectors = _finalize_and_write(
        writer, "sectors", factories.make_sectors_payload(), False, outcomes,
        provider="fmp", data_quality=1.0, generated_at=generated_at,
    )
    calendar = _finalize_and_write(
        writer, "calendar", factories.make_calendar_payload(), False, outcomes,
        provider="fred", data_quality=1.0, generated_at=generated_at,
    )

    dashboard_payload = _build_dashboard(
        risk_env=risk_env, equities=equities, crypto=crypto, sectors=sectors, calendar=calendar,
    )
    _finalize_and_write(
        writer, "dashboard", dashboard_payload, False, outcomes,
        provider="derived", data_quality=1.0, generated_at=generated_at,
    )


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    from pipeline.storage import StorageWriter

    root = tmp_path / "data"
    _publish(StorageWriter(root), FROZEN_TS)
    return root


def test_run_write_path_manifest_is_stable(data_root: Path) -> None:
    if not GOLDEN.exists():
        pytest.fail("golden manifest missing; run python tests/pipeline/record_golden.py")
    manifest = _manifest(data_root)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert manifest == expected, (
        "published bytes drifted (#192): "
        f"missing={sorted(set(expected) - set(manifest))} "
        f"extra={sorted(set(manifest) - set(expected))} "
        f"changed={sorted(k for k in set(manifest) & set(expected) if manifest[k] != expected[k])}"
    )
