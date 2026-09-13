"""Shared engine for the #192 golden byte-manifest lock.

Lives OUTSIDE test_run_golden.py so scripts/record_golden.py can drive the exact
same publish sequence without importing a test module (and transitively pytest).
The test asserts against the recorded manifest; the script regenerates it - both
MUST publish identically, which this module guarantees by being the only copy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.pipeline import factories

FROZEN_TS = "2026-08-22T12:00:00Z"


def manifest(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# Freeze the pipeline's canonical UTC clock for the synthetic run. validation/freshness.py
# evaluates the freshness ladder against now_utc(); without freezing it the published
# freshness_status drifts with real time and the #192 byte-manifest lock can never reproduce
# the golden. Both consumers below must resolve now_utc via their module attribute, which the
# patches target, so the frozen timestamp is what the write path sees.
@patch("pipeline.storage.outcomes.now_utc")
@patch("pipeline.validation.freshness.now_utc")
def publish(writer, generated_at: str, frozen_freshness_now: Any, frozen_outcomes_now: Any) -> None:
    """The write sequence main() performs for the full command, narrowed to datasets that
    cover every assembly branch: risk (derived inputs), market fallback provenance, news
    default provider, calendar detail, dashboard aggregation."""
    frozen_outcomes_now.return_value = generated_at
    frozen_freshness_now.return_value = generated_at
    from pipeline.run import (
        RunOutcomes,
        _build_dashboard,
        _finalize_and_write,
        _publish_metadata,
        _run_scope,
    )

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
    _publish_metadata(writer, outcomes)
