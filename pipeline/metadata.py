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

def row_count_for(name: str, payload: Any) -> int | None:
    """Rows carried by a registered payload under its DatasetSpec.row_key (#89).

    The ONE implementation of this question. run.py's envelope assembly and
    scripts/backfill_metadata.py must answer it identically - two hand-copied versions
    had already diverged (one returned 0 where the other returns None, which is the
    difference between "empty" and "not applicable") before this helper absorbed
    them (#188). Derived datasets (risk, dashboard) are single objects: they get
    None and skip the emptiness check rather than being scored empty forever.

    The registry import is function-local to avoid a schemas/metadata import cycle.
    """
    from pipeline.schemas import registry as dataset_registry

    spec = dataset_registry.BY_KEY.get(name)
    if spec is None or not spec.row_counted or spec.row_key is None:
        return None
    rows = payload.get(spec.row_key) if isinstance(payload, dict) else getattr(payload, spec.row_key, None)
    if isinstance(rows, (list, tuple, dict)):
        return len(rows)
    return None
