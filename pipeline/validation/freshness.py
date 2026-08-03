"""Freshness five-state determination (architecture §8.5 single authoritative implementation).

The pipeline determines freshness uniformly in validation/freshness.py (not trusting Provider
self-reporting, architecture §8.4); analysis/freshness.py reuses this module.

Unified determination (P1-7): Collectors no longer fill freshness_status themselves; after writing,
this module recomputes against the expected frequency from config/sources.yaml (fresh/delayed/stale/
missing/degraded five states), then persists to metadata/freshness.json and each envelope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

FreshnessStatus = Literal["fresh", "delayed", "stale", "missing", "degraded"]


def evaluate_freshness(
    updated_at: str | None,
    expected_minutes: int,
    now: datetime | None = None,
) -> FreshnessStatus:
    """Time-dimension five-state determination (relative to the expected update frequency; no degraded).

    - fresh   : latest update ≤ 1.5× expected interval
    - delayed : 1.5× ~ 3×
    - stale   : > 3×
    - missing : never had data / file missing
    """
    if not updated_at:
        return "missing"
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return "missing"
    if now is None:
        now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    age_minutes = (now - updated).total_seconds() / 60.0
    if age_minutes <= 1.5 * expected_minutes:
        return "fresh"
    if age_minutes <= 3.0 * expected_minutes:
        return "delayed"
    return "stale"


def finalize_freshness(
    dataset: str,
    generated_at: str | None,
    degraded: bool,
    missing: bool = False,
    now: datetime | None = None,
) -> FreshnessStatus:
    """Unified five-state determination (P1-7, architecture §8.5 table semantics).

    Priority:
    1. missing   —— never had data / file missing (explicit marker)
    2. degraded  —— some Provider degraded/fallback (independent of time)
    3. fresh/delayed/stale —— time-dimension determination by expected update frequency (config/sources.yaml)
    """
    if missing or not generated_at:
        return "missing"
    if degraded:
        return "degraded"
    return evaluate_freshness(generated_at, expected_interval_minutes_for(dataset, 480), now)


def expected_interval_minutes_for(dataset: str, fallback: int) -> int:
    """Read the expected interval (minutes) from config/sources.yaml."""
    from pipeline.settings import settings

    try:
        expectations = settings.load_sources().get("expectations", {})
        entry = expectations.get(dataset, {})
        minutes = int(entry.get("interval_minutes", fallback))
        return minutes if minutes > 0 else fallback
    except (FileNotFoundError, ValueError, TypeError):
        return fallback
