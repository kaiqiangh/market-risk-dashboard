"""Calendar collector (architecture §3.7 CalendarCollector: economic calendar + earnings calendar).

#94 (uses #83): two registry calls feed one payload —

- **earnings** (domain ``calendar``): FMP stable primary → Nasdaq fallback (restores the
  BMO/AMC session signal FMP dropped). yfinance fallback retired (#83: structurally empty).
- **economic** (domain ``economic``): FRED release dates (allowlisted release ids) + the
  official FOMC meeting calendar.

Every event carries an unambiguous UTC instant (pipeline.utils.et_instant /
earnings_instant); the frontend groups by the local day of that instant. Events are
deduplicated by their stable id — first (higher-priority) source wins — so the same
earnings row arriving from both FMP and Nasdaq, or the same release from overlapping
sources, can never double-publish. An upstream that answers with zero rows publishes
``events: []`` and the freshness layer scores it ``empty``, never ``fresh`` (#89/#101).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pipeline.metadata import quality_for_outcomes
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import CalendarDataset, CalendarEnvelope, CalendarEvent
from pipeline.settings import Settings
from pipeline.utils import earnings_instant, et_instant, now_utc


class CalendarCollector:
    def __init__(self, registry: ProviderRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings or Settings()
        self.degraded: list[str] = []
        self.provider_status: dict[str, Any] = {}

    # ---- Summary ----

    def _quality(self, outcomes: dict[str, dict[str, Any]] | None = None) -> float:
        """Quality is scoped to the calendar's earnings and economic outcomes."""
        local = outcomes or {}
        return quality_for_outcomes(
            [
                bool(meta.get("degraded") or meta.get("used_fallback") or meta.get("from_cache"))
                for meta in local.values()
            ],
            settings=self.settings,
        )

    def collect(self) -> tuple[CalendarEnvelope, dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        start = today.isoformat()
        # #102 (M-5): the horizon is config (operations.calendar_horizon_days), not a literal.
        horizon = int(self.settings.load_sources_config().operations.calendar_horizon_days)
        end = (today + timedelta(days=horizon)).isoformat()
        # #94 (N-2): the cache key names the actual window — `earnings_7d` used to lie
        # about a 14-day horizon.
        earnings_key = f"earnings_{horizon}d"
        economic_key = f"economic_{horizon}d"

        events: list[CalendarEvent] = []
        outcomes: dict[str, dict[str, Any]] = {}
        malformed = 0

        # ---- Earnings (calendar domain: FMP → Nasdaq) ----
        try:
            out = self.registry.call("calendar", "get_earnings_calendar", earnings_key, args=(start, end))
            self.provider_status["calendar"] = out["meta"]
            if out["meta"].get("degraded"):
                self.degraded.append("calendar/earnings: provider served degraded data")
            outcomes["earnings"] = {
                "provider": str(out["meta"].get("provider", "unavailable")),
                "used_fallback": bool(out["meta"].get("used_fallback", False)),
                "from_cache": bool(out["meta"].get("from_cache", False)),
                "degraded": bool(out["meta"].get("degraded", False)),
            }
            provider_name = str(out["meta"].get("provider", "unavailable"))
            for row in out["result"]:
                symbol = str(row["symbol"])
                day = str(row["date"])
                events.append(
                    CalendarEvent(
                        id=f"earnings-{symbol}-{day}",
                        type="earnings",
                        title=f"{symbol} Earnings",
                        country="US",
                        datetime=earnings_instant(day, row.get("session")),
                        importance="medium",
                        actual=row.get("eps_actual"),
                        forecast=row.get("eps_estimate"),
                        previous=None,
                        unit="usd",
                        related_assets=[symbol],
                        source=provider_name,
                    )
                )
        except ProviderError as exc:
            self.degraded.append(f"calendar/earnings: {exc}")
            failure = {"degraded": True, "error": str(exc), "provider": "unavailable"}
            self.provider_status["calendar"] = failure
            outcomes["earnings"] = failure

        # ---- Economic (economic domain: FRED releases + FOMC) ----
        try:
            eco = self.registry.call("economic", "get_economic_calendar", economic_key, args=(start, end))
            self.provider_status["economic"] = eco["meta"]
            if eco["meta"].get("degraded"):
                self.degraded.append("calendar/economic: provider served degraded data")
            outcomes["economic"] = {
                "provider": str(eco["meta"].get("provider", "unavailable")),
                "used_fallback": bool(eco["meta"].get("used_fallback", False)),
                "from_cache": bool(eco["meta"].get("from_cache", False)),
                "degraded": bool(eco["meta"].get("degraded", False)),
            }
            for row in eco["result"]:
                try:
                    events.append(
                        CalendarEvent(
                            id=str(row["id"]),
                            type="economic",
                            title=str(row["title"]),
                            country=str(row.get("country") or "US"),
                            datetime=et_instant(str(row["date"]), str(row["time_et"])),
                            importance=row.get("importance", "medium"),
                            actual=None,
                            forecast=None,
                            previous=None,
                            unit=None,
                            related_assets=[],
                            source=str(row.get("source") or "fred"),
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    # A malformed upstream row must degrade the row, never crash the run.
                    malformed += 1
        except ProviderError as exc:
            self.degraded.append(f"calendar/economic: {exc}")
            failure = {"degraded": True, "error": str(exc), "provider": "unavailable"}
            self.provider_status["economic"] = failure
            outcomes["economic"] = failure

        # ---- Dedupe by stable id: first (higher-priority) source wins (#94) ----
        seen: dict[str, CalendarEvent] = {}
        for ev in events:
            if ev.id not in seen:
                seen[ev.id] = ev
        dropped = len(events) - len(seen)
        events = list(seen.values())
        events.sort(key=lambda e: e.datetime)

        if malformed:
            self.degraded.append(f"calendar/economic: {malformed} malformed row(s)")
            outcomes.setdefault("economic", {"provider": "unavailable"})["degraded"] = True

        # ---- Provenance: the answering source of record. Both domains feed calendar.json,
        # so the outcome names whichever answered (earnings primary; economic if earnings
        # failed) — never a hardcoded "fmp" that could lie about a FRED-only payload.
        if outcomes:
            providers = {
                str(item.get("provider", "unavailable"))
                for item in outcomes.values()
                if str(item.get("provider", "unavailable")) != "unavailable"
            }
            provider_outcome = {
                "provider": next(iter(providers)) if len(providers) == 1 else "mixed" if providers else "unavailable",
                "used_fallback": any(bool(item.get("used_fallback")) for item in outcomes.values()),
                "from_cache": any(bool(item.get("from_cache")) for item in outcomes.values()),
            }
        else:
            provider_outcome = {"provider": "unavailable", "used_fallback": False, "from_cache": False}

        quality = self._quality(outcomes)
        # #64: return payload + provider outcome; the caller assembles the envelope and
        # finalizes freshness through the single assembly path.
        payload = CalendarDataset(events=events, updated_at=now_utc())
        return payload, {
            "degraded": self.degraded,
            "provider_status": self.provider_status,
            "provider_outcome": provider_outcome,
            "provider_outcomes": outcomes,
            "data_quality": round(quality, 3),
            "source_updated_at": None,
            "deduped": dropped,
            "malformed": malformed,
        }
