"""Economic calendar provider: FRED release dates + the Federal Reserve's FOMC calendar (#94).

Chosen in #83 (§3A/§3C): FRED is the primary for US macro release *dates* — the key is
already in the repo, the data is US-government (free to redistribute), every release row
has a stable id (`release_id` + `date`), and the API's `realtime_start/end` bounds the
window server-side (verified live: 1 call per release, ~8 calls per run). FOMC meeting
dates come from the official page (2026/2027 both published, no key, public domain).

Two traps from #83, encoded here: `release_id=101` (FOMC Press Release) is NOT the FOMC
meeting calendar — FOMC comes from the federalreserve.gov page; and the FRED list is
driven from an explicit `release_id` allowlist, never the unfiltered `/releases/dates`.

FRED gives *dates only* — the per-release ET release time is attached here as a constant
and the collector converts (date, ET) → UTC (pipeline.utils.et_instant).
"""

from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

from pipeline.providers._util import UA, _today
from pipeline.providers.base import (
    BaseProvider,
    ProviderError,
    ProviderHealth,
)

FRED_BASE = "https://api.stlouisfed.org/fred"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
#: release_id allowlist (verified live 2026-08-07) → (name, ET release time, importance).
#: The names are stable public release titles; the ids are immutable.
RELEASES: dict[int, tuple[str, str, str]] = {
    10: ("Consumer Price Index", "08:30", "high"),
    50: ("Employment Situation", "08:30", "high"),
    54: ("Personal Income and Outlays", "08:30", "high"),
    46: ("Producer Price Index", "08:30", "high"),
    53: ("Gross Domestic Product", "08:30", "high"),
    9: ("Advance Retail Sales", "08:30", "high"),
    192: ("Job Openings and Labor Turnover Survey", "10:00", "medium"),
}

_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


class FredCalendarProvider(BaseProvider):
    name = "fred_calendar"
    domain = "economic"
    hosts = ("api.stlouisfed.org", "www.federalreserve.gov")

    def __init__(self, settings=None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.fred_api_key
        from pipeline.providers.base import guarded_client

        self._client = guarded_client(set(self.hosts), timeout=15.0, headers={"User-Agent": UA})

    def health(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(provider=self.name, ok=False, error="missing DATA_FRED_API_KEY", checked_at=None)
        started = time.monotonic()
        try:
            # Cheap probe: ONE release for today's window — not the full 8-call economic
            # calendar (the per-call limiter is for the run, not for health checks).
            rows = self._fred_release_dates(10, _today(), _today())
            ok = isinstance(rows, list)
            return ProviderHealth(
                provider=self.name, ok=ok,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=None if ok else "bad payload", checked_at=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                provider=self.name, ok=False,
                latency_ms=round((time.monotonic() - started) * 1000, 1),
                error=str(exc)[:200], checked_at=None,
            )

    def get_economic_calendar(self, start: str, end: str) -> list[dict[str, Any]]:
        """Economic-event rows in the shared shape (id/title/date/time_et/importance/source).

        FRED release dates + FOMC meeting dates, filtered to ``[start, end]``, sorted by
        date. Retries live in ProviderRegistry.call (#103/E-3).

        Sources are isolated: one failing release (or the FOMC page) never discards the
        rows already fetched — the calendar must not be empty because its most fragile
        (scraped) source hiccupped. An error is raised only when *every* source failed.
        """
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for release_id in RELEASES:
            try:
                rows.extend(self._fred_release_dates(release_id, start, end))
            except ProviderError as exc:
                errors.append(f"release {release_id}: {exc}")
        try:
            rows.extend(self._fomc_meetings(start, end))
        except ProviderError as exc:
            errors.append(f"fomc: {exc}")
        rows.sort(key=lambda r: (r["date"], r["time_et"]))
        if not rows and errors:
            raise ProviderError("FRED calendar all sources failed: " + "; ".join(errors[:3]))
        return rows

    # ---- FRED release dates ----

    def _fred_release_dates(self, release_id: int, start: str, end: str) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ProviderError("FRED calendar: missing DATA_FRED_API_KEY (local .env)")
        name, time_et, importance = RELEASES[release_id]
        resp = self._client.get(
            f"{FRED_BASE}/release/dates",
            params={
                "release_id": release_id,
                "api_key": self.api_key,
                "file_type": "json",
                "include_release_dates_with_no_data": "true",
                "sort_order": "asc",
                # #83: the realtime window bounds the *release dates* server-side — without
                # it the API returns the full 1949→today history for a release.
                "realtime_start": start,
                "realtime_end": end,
            },
        )
        if resp.status_code != 200:
            # #103/S-1: one error boundary — classification + redaction (from_http).
            raise ProviderError.from_http(f"FRED release {release_id}", resp)
        data = resp.json()
        rows = data.get("release_dates") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError(f"FRED release {release_id}: unexpected payload")
        out: list[dict[str, Any]] = []
        for row in rows:
            day = str(row.get("date", ""))
            if not day:
                continue
            out.append(
                {
                    "id": f"econ-fred-{release_id}-{day}",
                    "title": name,
                    "date": day,
                    "time_et": time_et,
                    "importance": importance,
                    "country": "US",
                    "source": "fred",
                }
            )
        return out

    # ---- FOMC meetings (federalreserve.gov, official) ----

    def _fomc_meetings(self, start: str, end: str) -> list[dict[str, Any]]:
        """Parse the official FOMC calendar page into decision-day events.

        Statement lands 14:00 ET on the **second** day of each meeting (#83 §3C); the
        ``*`` press-conference marker is the presence of a ``fomcpressconf`` link.
        """
        resp = self._client.get(FOMC_CALENDAR_URL)
        if resp.status_code != 200:
            # #103/S-1: one error boundary — classification + redaction (from_http).
            raise ProviderError.from_http("FOMC calendar", resp)
        html = resp.text
        out: list[dict[str, Any]] = []
        sections = _year_sections(html)
        if not sections:
            raise ProviderError("FOMC calendar parse returned no year sections")
        for idx, (section_start, year) in enumerate(sections):
            section_end = sections[idx + 1][0] if idx + 1 < len(sections) else len(html)
            section = html[section_start:section_end]
            months = list(re.finditer(r"fomc-meeting__month[^>]*>\s*<strong>(\w+)</strong>", section))
            for midx, m in enumerate(months):
                month = _MONTHS.get(m.group(1))
                if month is None:
                    continue
                date_m = re.search(r"fomc-meeting__date[^>]*>\s*([\d-]+)\s*</div>", section[m.end():])
                if date_m is None:
                    continue
                day_range = date_m.group(1)
                days = [int(d) for d in re.findall(r"\d+", day_range)]
                if not days:
                    continue
                decision_day = days[1] if len(days) >= 2 else days[0]  # statement on the SECOND day
                block_end = months[midx + 1].start() if midx + 1 < len(months) else len(section)
                # date_m offsets are relative to the slice after the month marker — add
                # m.end() back to address the span within the section.
                press_conf = "fomcpressconf" in section[m.end() + date_m.end():block_end]
                try:
                    day = date(year, month, decision_day).isoformat()
                except ValueError:
                    continue  # e.g. a past year's malformed row — skip, never crash the run
                if not (start <= day <= end):
                    continue
                title = "FOMC Meeting" + (" (press conference)" if press_conf else "")
                out.append(
                    {
                        "id": f"econ-fomc-{day}",
                        "title": title,
                        "date": day,
                        "time_et": "14:00",
                        "importance": "high",
                        "country": "US",
                        "source": "fomc",
                    }
                )
        if not out:
            raise ProviderError("FOMC calendar parse returned no meeting rows")
        return out


def _year_sections(html: str) -> list[tuple[int, int]]:
    """``(section_start, year)`` for each ``YYYY FOMC Meetings`` panel heading."""
    out: list[tuple[int, int]] = []
    for m in re.finditer(r"<h4><a id=\"\d+\">(\d{4}) FOMC Meetings</a></h4>", html):
        out.append((m.end(), int(m.group(1))))
    return out
