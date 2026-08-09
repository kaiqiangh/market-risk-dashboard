"""CalendarCollector (#94): two-source merge, dedupe by id, session instants, honest empty."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.collectors.calendar import CalendarCollector
from pipeline.providers.base import ProviderError
from pipeline.settings import Settings


class _FakeRegistry:
    """Stub of ProviderRegistry.call: canned results per (domain, method)."""

    def __init__(self, earnings=None, economic=None, earnings_error=None, economic_error=None) -> None:
        self.earnings = earnings or []
        self.economic = economic or []
        self.earnings_error = earnings_error
        self.economic_error = economic_error
        self.degraded_domains: set[str] = set()
        self.calls: list[tuple[str, str, str]] = []

    def call(self, domain: str, method: str, key: str, args=()):
        self.calls.append((domain, method, key))
        if domain == "calendar":
            if self.earnings_error:
                raise ProviderError(self.earnings_error)
            return {"result": self.earnings, "meta": {"provider": "fmp", "used_fallback": False, "from_cache": False}}
        if domain == "economic":
            if self.economic_error:
                raise ProviderError(self.economic_error)
            return {"result": self.economic, "meta": {"provider": "fred_calendar", "used_fallback": False, "from_cache": False}}
        raise AssertionError(f"unexpected domain {domain}")


def _collector(registry: _FakeRegistry, tmp_path: Path) -> CalendarCollector:
    return CalendarCollector(registry, Settings(_env_file=None, artifacts_dir=tmp_path))


EARNINGS = [
    {"symbol": "AAPL", "date": "2026-08-12", "eps_estimate": 2.31, "eps_actual": None,
     "revenue_estimate": None, "revenue_actual": None, "session": "BMO"},
    {"symbol": "CSCO", "date": "2026-08-12", "eps_estimate": 0.99, "eps_actual": None,
     "revenue_estimate": None, "revenue_actual": None, "session": "AMC"},
]
ECONOMIC = [
    {"id": "econ-fred-10-2026-08-12", "title": "Consumer Price Index", "date": "2026-08-12",
     "time_et": "08:30", "importance": "high", "country": "US", "source": "fred"},
    {"id": "econ-fomc-2026-09-16", "title": "FOMC Meeting (press conference)", "date": "2026-09-16",
     "time_et": "14:00", "importance": "high", "country": "US", "source": "fomc"},
]


def test_collects_earnings_and_economic_with_utc_instants(tmp_path: Path) -> None:
    registry = _FakeRegistry(earnings=EARNINGS, economic=ECONOMIC)
    payload, meta = _collector(registry, tmp_path).collect()

    assert [c[:2] for c in registry.calls] == [("calendar", "get_earnings_calendar"), ("economic", "get_economic_calendar")]
    # N-2: the cache key names the real 14-day horizon, not the old lying earnings_7d.
    assert registry.calls[0][2] == "earnings_14d"
    assert registry.calls[1][2] == "economic_14d"

    by_id = {e.id: e for e in payload.events}
    assert len(by_id) == 4
    # AAPL BMO → 09:30 ET → 13:30Z (EDT); CSCO AMC → 16:00 ET → 20:00Z (EDT);
    # CPI 08:30 ET → 12:30Z; FOMC 14:00 ET on 2026-09-16 → 18:00Z (EST).
    assert by_id["earnings-AAPL-2026-08-12"].datetime == "2026-08-12T13:30:00Z"
    assert by_id["earnings-CSCO-2026-08-12"].datetime == "2026-08-12T20:00:00Z"
    assert by_id["econ-fred-10-2026-08-12"].datetime == "2026-08-12T12:30:00Z"
    assert by_id["econ-fomc-2026-09-16"].datetime == "2026-09-16T18:00:00Z"
    assert by_id["econ-fred-10-2026-08-12"].importance == "high"
    assert by_id["econ-fred-10-2026-08-12"].source == "fred"
    assert by_id["earnings-AAPL-2026-08-12"].source == "fmp"
    # sorted by instant.
    assert [e.datetime for e in payload.events] == sorted(e.datetime for e in payload.events)
    assert meta["degraded"] == []
    assert meta["provider_outcome"]["provider"] == "mixed"
    assert set(meta["provider_outcomes"]) == {"earnings", "economic"}


def test_dedupe_by_id_keeps_first_source(tmp_path: Path) -> None:
    """Same event arriving from two sources (earnings-{symbol}-{date} from FMP + Nasdaq)
    must publish once — the higher-priority (first) row wins."""
    fmp_row = dict(EARNINGS[0], session=None)
    nasdaq_row = dict(EARNINGS[0], session="AMC")  # same id, later source
    registry = _FakeRegistry(earnings=[fmp_row, nasdaq_row], economic=[])
    payload, meta = _collector(registry, tmp_path).collect()

    events = [e for e in payload.events if e.id == "earnings-AAPL-2026-08-12"]
    assert len(events) == 1
    # The FMP (primary) row won → neutral noon instant, not the fallback's AMC time.
    assert events[0].datetime == "2026-08-12T12:00:00Z"
    assert meta["deduped"] == 1


def test_session_absent_falls_back_to_noon_utc(tmp_path: Path) -> None:
    row = dict(EARNINGS[0], session=None)
    payload, _ = _collector(_FakeRegistry(earnings=[row], economic=[]), tmp_path).collect()
    assert payload.events[0].datetime == "2026-08-12T12:00:00Z"


def test_earnings_failure_is_degraded_but_economic_survives(tmp_path: Path) -> None:
    registry = _FakeRegistry(earnings_error="FMP calendar HTTP 403", economic=ECONOMIC)
    payload, meta = _collector(registry, tmp_path).collect()

    assert len(payload.events) == 2  # economic only
    assert meta["provider_status"]["calendar"]["degraded"] is True
    assert any("FMP calendar HTTP 403" in d for d in meta["degraded"])
    # Provenance names the source that actually answered (never a hardcoded "fmp").
    assert meta["provider_outcome"]["provider"] == "fred_calendar"
    assert meta["provider_outcomes"]["earnings"]["degraded"] is True
    assert meta["provider_outcomes"]["economic"]["provider"] == "fred_calendar"


def test_both_fail_publishes_unavailable_outcome(tmp_path: Path) -> None:
    registry = _FakeRegistry(earnings_error="boom", economic_error="bam")
    payload, meta = _collector(registry, tmp_path).collect()
    assert payload.events == []
    assert meta["provider_outcome"]["provider"] == "unavailable"
    assert len(meta["degraded"]) == 2


def test_malformed_economic_row_is_skipped_not_fatal(tmp_path: Path) -> None:
    bad = {"id": "econ-fred-9-2026-08-14", "title": "Advance Retail Sales", "date": "not-a-date",
           "time_et": "08:30", "importance": "high", "country": "US", "source": "fred"}
    registry = _FakeRegistry(earnings=[], economic=[bad, ECONOMIC[0]])
    payload, meta = _collector(registry, tmp_path).collect()
    assert [e.id for e in payload.events] == ["econ-fred-10-2026-08-12"]
    assert meta["malformed"] == 1


def test_both_sources_down_publishes_empty_not_fresh(tmp_path: Path) -> None:
    registry = _FakeRegistry(earnings_error="boom", economic_error="bam")
    payload, meta = _collector(registry, tmp_path).collect()

    assert payload.events == []
    assert len(meta["degraded"]) == 2
    # The freshness layer scores row_count=0 as `empty`/`missing`, never `fresh` (#89/#101).
    from pipeline.utils import now_utc
    from pipeline.validation.freshness import finalize_freshness

    verdict = finalize_freshness("calendar", now_utc(), False, row_count=len(payload.events))
    assert verdict.status == "empty"


def test_zero_rows_success_is_empty_not_degraded(tmp_path: Path) -> None:
    """A quiet week (upstream alive, zero rows) is `empty`, not an error (#89)."""
    registry = _FakeRegistry(earnings=[], economic=[])
    payload, meta = _collector(registry, tmp_path).collect()
    assert payload.events == []
    assert meta["degraded"] == []
