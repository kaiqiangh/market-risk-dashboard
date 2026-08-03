"""Pipeline shared utilities (architecture §8.2 time convention).

All raw times are ISO 8601 UTC with a Z suffix (`2026-08-03T10:00:00Z`).
`now_utc()` is the single authoritative implementation across the pipeline (P2-8: removes 13 duplicate `_now_utc` definitions).
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> str:
    """Current UTC time, ISO 8601 + Z (architecture §8.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
