"""Pure dataset metadata helpers for scoped quality and honest provenance."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pipeline.degrade import degraded_quality
from pipeline.settings import Settings


def quality_for_outcomes(outcomes: Iterable[bool], *, settings: Settings | None = None) -> float:
    """Apply the configured quality factor to local degraded outcomes only."""
    return round(degraded_quality(sum(bool(outcome) for outcome in outcomes), settings=settings), 3)


def normalize_source_timestamp(value: Any) -> str | None:
    """Normalize a provider observation timestamp or date; reject unknown values."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if len(raw) == 10:
        raw = f"{raw}T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def oldest_source_timestamp(values: Iterable[Any]) -> str | None:
    """Return the oldest contributing source time, or null if any input is unknown."""
    raw_values = list(values)
    normalized = [normalize_source_timestamp(value) for value in raw_values]
    if not normalized or any(value is None for value in normalized):
        return None
    return min(normalized)


def latest_row_timestamp(rows: Iterable[dict[str, Any]], field: str = "date") -> str | None:
    """Return the newest valid observation date in a provider history slice."""
    values = [normalize_source_timestamp(row.get(field)) for row in rows]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else None
