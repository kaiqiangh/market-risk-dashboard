"""Pipeline shared utilities (architecture §8.2 time convention).

All raw times are ISO 8601 UTC with a Z suffix (`2026-08-03T10:00:00Z`).
`now_utc()` is the single authoritative implementation across the pipeline (P2-8: removes 13 duplicate `_now_utc` definitions).

Timezone handling for the calendar (#94): FRED and the FOMC page publish **dates only**
(or dates + US-Eastern release times), and the frontend groups events by the *local* day.
Every published event therefore carries an unambiguous UTC instant, produced here by
`et_instant()` (ET → UTC, DST-aware) and `earnings_instant()` (session → ET → UTC).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

#: US Eastern (America/New_York) — DST-aware via the system tz database.
_ET = ZoneInfo("America/New_York")

#: Earnings sessions → ET release time (Nasdaq vocabulary, #83 §3E). The neutral fallback
#: (no session signal, e.g. FMP stable) is 12:00 UTC — an unambiguous midday instant.
EARNINGS_SESSION_ET: dict[str | None, str | None] = {
    "BMO": "09:30",
    "AMC": "16:00",
    None: None,
}


def now_utc() -> str:
    """Current UTC time, ISO 8601 + Z (architecture §8.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def et_instant(date_str: str, time_et: str) -> str:
    """The UTC instant of ``(date, HH:MM)`` in US Eastern, as ISO 8601 + Z.

    DST-aware: 2026-08-12 08:30 ET → 12:30Z (EDT, UTC−4); 2026-12-10 14:00 ET → 19:00Z
    (EST, UTC−5). This is the single conversion point for calendar events (#94) — the
    frontend then groups by the local day of this instant.
    """
    naive = datetime.fromisoformat(f"{date_str}T{time_et}:00")
    return naive.replace(tzinfo=_ET).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def earnings_instant(date_str: str, session: str | None) -> str:
    """The UTC instant of an earnings event: BMO 09:30 ET, AMC 16:00 ET, or 12:00 UTC
    when the source carries no session signal (FMP stable dropped ``time``, #83)."""
    et_time = EARNINGS_SESSION_ET.get(session)
    if et_time is None:
        return f"{date_str}T12:00:00Z"
    return et_instant(date_str, et_time)
