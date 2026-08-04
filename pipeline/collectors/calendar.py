"""Calendar collector (architecture §3.7 CalendarCollector: economic calendar + earnings calendar).

MVP: earnings calendar from FMP (→ yfinance fallback); economic calendar sources are limited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from pipeline.degrade import degraded_quality
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import CalendarDataset, CalendarEnvelope, CalendarEvent
from pipeline.settings import Settings
from pipeline.utils import now_utc


class CalendarCollector:
    def __init__(self, registry: ProviderRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings or Settings()
        self.degraded: list[str] = []
        self.provider_status: dict[str, Any] = {}

    # ---- Summary ----

    def _quality(self) -> float:
        """Data quality degrades by the configured factor when the calendar source degraded.

        The calendar has a single logical source, so any number of failures counts as one.
        """
        return degraded_quality(1 if self.degraded else 0, settings=self.settings)

    def collect(self) -> tuple[CalendarEnvelope, dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        start = today.isoformat()
        end = (today + timedelta(days=14)).isoformat()
        events: list[CalendarEvent] = []

        try:
            out = self.registry.call("calendar", "get_earnings_calendar", "earnings_7d", args=(start, end))
            self.provider_status["calendar"] = out["meta"]
            for row in out["result"]:
                events.append(
                    CalendarEvent(
                        id=f"earnings-{row['symbol']}-{row['date']}",
                        type="earnings",
                        title=f"{row['symbol']} Earnings",
                        country="US",
                        datetime=f"{row['date']}T12:00:00Z",
                        importance="medium",
                        actual=row.get("eps_actual"),
                        forecast=row.get("eps_estimate"),
                        previous=None,
                        unit="usd",
                        related_assets=[row["symbol"]],
                        source=out["meta"].get("provider", "fmp"),
                    )
                )
        except ProviderError as exc:
            self.degraded.append(f"calendar: {exc}")
            self.provider_status["calendar"] = {"degraded": True, "error": str(exc)}

        quality = self._quality()
        # #64: return payload + provider outcome; the caller assembles the envelope and
        # finalizes freshness through the single assembly path.
        payload = CalendarDataset(events=events, updated_at=now_utc())
        return payload, {
            "degraded": self.degraded,
            "provider_status": self.provider_status,
            "source": ["fmp", "yfinance"],
            "data_quality": round(quality, 3),
        }


