"""Freshness six-state determination (architecture §8.5 single authoritative implementation).

The pipeline determines freshness uniformly in validation/freshness.py (not trusting Provider
self-reporting, architecture §8.4); analysis/freshness.py reuses this module.

Unified determination (P1-7): Collectors no longer fill freshness_status themselves; after writing,
this module recomputes against the expected frequency from config/sources.yaml (fresh/delayed/stale/
missing/degraded/empty six states), then persists to metadata/freshness.json and each envelope.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import NamedTuple

from pipeline.schemas.envelope import (
    STATUS_RANK,
    FreshnessReason,
    FreshnessStatus,
    ReasonCode,
)

# Precedence for aggregating a composite dataset's freshness comes from
# :data:`pipeline.schemas.envelope.STATUS_RANK` — the one copy of the severity map, shared
# with ``storage/outcomes.py`` (they were byte-identical copies before #101). A composite is
# only as fresh as its stalest input, so the worst status among its constituents wins.


class FreshnessVerdict(NamedTuple):
    """The single authoritative answer to "how fresh is this dataset, and why".

    Produced only by :func:`finalize_freshness`. Both ``metadata/freshness.json`` and
    ``metadata/sources.json`` are rendered from verdicts, which is what stops the two files
    contradicting each other the way they did before #89.
    """

    status: FreshnessStatus
    reason: FreshnessReason


#: Clock-skew tolerance. A timestamp up to this far in the *future* is treated as current
#: (producer clock slightly ahead); anything further ahead cannot certify freshness — a
#: bogus or hostile timestamp must degrade loudly, not vouch for itself.
FUTURE_SKEW_TOLERANCE_MINUTES = 5.0


def is_future_beyond_skew(updated_at: str | None, now: datetime | None = None) -> bool:
    """True when updated_at lies further ahead than FUTURE_SKEW_TOLERANCE_MINUTES.

    The shared predicate behind the stale verdict in evaluate_freshness and the
    distinguishing detail finalize_freshness attaches (#187 review): one definition,
    so the status decision and its operator-facing explanation can never disagree.
    Malformed or absent timestamps are simply not future - the status ladder answers
    for them.
    """
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (updated - now).total_seconds() / 60.0 > FUTURE_SKEW_TOLERANCE_MINUTES


def evaluate_freshness(
    updated_at: str | None,
    expected_minutes: int,
    now: datetime | None = None,
) -> FreshnessStatus:
    """Time-dimension five-state determination (relative to the expected update frequency; no degraded).

    - fresh   : latest update ≤ 1.5× expected interval
    - delayed : 1.5× ~ 3×
    - stale   : > 3× (including a timestamp further ahead than the skew tolerance)
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
    if age_minutes < -FUTURE_SKEW_TOLERANCE_MINUTES:
        # Future-dated beyond skew tolerance: never fresh, whatever the naive arithmetic says.
        return "stale"
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
    *,
    row_count: int | None = None,
    error_code: str | None = None,
    detail: str = "",
    used_fallback: bool = False,
    from_cache: bool = False,
) -> FreshnessVerdict:
    """Unified six-state determination — the only producer of status *and* reason (#89).

    Priority:

    1. ``missing``  — never had data / file missing (explicit marker, or no ``generated_at``)
    2. ``empty``    — the upstream answered with zero rows. If the run *also* had to degrade
       to reach that answer, it is ``missing`` instead: an empty result that required a
       fallback is not a quiet week, it is a failure that happens to look like one.
    3. ``degraded`` — a provider degraded or fell back, but rows came back (time-independent)
    4. ``fresh`` / ``delayed`` / ``stale`` — the time ladder, against the expected interval
       for ``dataset`` in ``config/sources.yaml``

    ``row_count=None`` means "this dataset has no meaningful row cardinality" (``risk``,
    ``dashboard``) and skips the emptiness check. Passing ``0`` asserts genuine emptiness.

    This encodes the invariant that closed E-2: **``fresh`` requires a non-empty payload.**
    Before this, ``calendar.json`` published ``freshness_status: "fresh"`` with ``events: []``.
    """
    if missing or not generated_at:
        code = error_code or ("all_providers_failed" if degraded else "not_collected_this_run")
        return FreshnessVerdict("missing", _reason(code, detail))

    if row_count == 0:
        if degraded:
            code = error_code or "all_providers_failed"
            return FreshnessVerdict("missing", _reason(code, detail))
        code = error_code or ("no_events_in_window" if dataset == "calendar" else "no_rows_returned")
        return FreshnessVerdict("empty", _reason(code, detail))

    if degraded:
        if error_code:
            code = error_code
        elif from_cache:
            code = "served_from_cache"
        elif used_fallback:
            code = "served_from_fallback"
        else:
            code = "provider_http_error"
        return FreshnessVerdict("degraded", _reason(code, detail))

    status = evaluate_freshness(generated_at, expected_interval_minutes_for(dataset, 480), now)
    code = "ok" if status == "fresh" else "interval_exceeded"
    # A future-dated timestamp degrades to the same stale STATUS as a mundane late fetch,
    # but the closed reason vocabulary alone would mislabel the anomaly (#187 review): name
    # the actual event in the detail so an operator reads "clock/hostile timestamp", not
    # "provider was slow".
    if status == "stale" and is_future_beyond_skew(generated_at, now):
        marker = f"generated_at lies in the future beyond the {FUTURE_SKEW_TOLERANCE_MINUTES:g}min skew tolerance"
        detail = f"{marker}; {detail}" if detail else marker
    return FreshnessVerdict(status, _reason(error_code or code, detail))


#: Codes the caller may supply that are not in the closed vocabulary get coerced rather than
#: raising: a run must never die because a provider invented an error label.
_KNOWN_CODES: frozenset[str] = frozenset(ReasonCode.__args__)  # type: ignore[attr-defined]


def _reason(code: str, detail: str) -> FreshnessReason:
    """Build a reason, coercing an unknown code to ``provider_http_error``.

    ``detail`` is truncated to the contract's 200-character cap here rather than letting
    pydantic reject it — the cap exists to blunt accidental secret leakage (#92), and a leaky
    string should be shortened, not turned into a crash that skips writing metadata entirely.
    """
    safe_code = code if code in _KNOWN_CODES else "provider_http_error"
    return FreshnessReason(code=safe_code, detail=detail[:200])  # type: ignore[arg-type]


def aggregate_freshness(statuses: Iterable[str]) -> FreshnessStatus:
    """Aggregate per-dataset freshness into one status for a composite dataset.

    A composite (e.g. ``facts``) is only as fresh as its stalest input, so the worst
    (lowest-confidence) status among ``statuses`` wins. ``missing`` dominates because a
    composite cannot be sound if a constituent was never produced; ``degraded`` follows
    because a quality problem in any source taints the aggregation.

    Unlike :func:`finalize_freshness`, this does **not** compare anything against the wall
    clock, which is what makes a fact-layer rebuild deterministic: rebuilding from inputs
    that are all ``fresh`` yields ``fresh`` regardless of how much real time has elapsed
    since the inputs were first observed.
    """
    worst: str = "fresh"
    worst_rank = -1
    for status in statuses:
        # An unknown status outranks everything (len+1) rather than being silently treated as
        # healthy — the same fail-loudly stance as registry.require.
        rank = STATUS_RANK.get(str(status), len(STATUS_RANK) + 1)
        if rank > worst_rank:
            worst_rank = rank
            worst = str(status)
    return worst  # type: ignore[return-value]


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
