"""FRED economic-calendar provider (#94/#83): release dates allowlist + FOMC page parse."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from pipeline.providers.base import ProviderError
from pipeline.providers.fred_calendar import RELEASES, FredCalendarProvider
from pipeline.settings import Settings


def _provider(tmp_path: Path) -> FredCalendarProvider:
    provider = FredCalendarProvider(Settings(_env_file=None))
    provider.api_key = "test-fred-key"  # tests never touch the real .env
    return provider


class _Resp:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.request = httpx.Request("GET", "https://example.test")

    def json(self) -> Any:
        return self._payload


class _Client:
    def __init__(self, fred_by_release: dict[int, list[str]], fomc_html: str = "",
                 failing_releases: set[int] | None = None, fomc_fails: bool = False) -> None:
        self._fred_by_release = fred_by_release
        self._fomc_html = fomc_html
        self._failing_releases = failing_releases or set()
        self._fomc_fails = fomc_fails
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None) -> Any:
        params = params or {}
        self.calls.append((url, params))
        if "fomccalendars" in url:
            if self._fomc_fails:
                return _Resp(500)
            return _Resp(200, text=self._fomc_html)
        release_id = int(params.get("release_id", 0))
        if release_id in self._failing_releases:
            return _Resp(500)
        # Emulate the API's server-side realtime window: dates outside [start, end] are
        # never returned (verified live — the provider must send the params to get it).
        window_start = params.get("realtime_start", "")
        window_end = params.get("realtime_end", "")
        dates = [
            {"release_id": release_id, "date": d}
            for d in self._fred_by_release.get(release_id, [])
            if window_start <= d <= window_end
        ]
        return _Resp(200, {"count": len(dates), "release_dates": dates})


#: Realistic slice of fomccalendars.htm (structure verified live 2026-08-07).
FOMC_HTML = """
<div class="panel panel-default"><div class="panel-heading"><h4><a id="42828">2026 FOMC Meetings</a></h4></div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>January</strong></div>
    <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">27-28</div>
    <div class="col-xs-12 col-md-4 col-lg-2"><strong>Statement:</strong><br>
      <a href="/monetarypolicy/files/monetary20260128a1.pdf">PDF</a>
      <a href="/newsevents/pressreleases/monetary20260128a.htm">HTML</a></div>
    <div class="col-xs-12 col-md-4 col-lg-3"><a href="/monetarypolicy/fomcpressconf20260128.htm">Press Conference Transcript</a></div>
  </div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>March</strong></div>
    <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">17-18</div>
    <div class="col-xs-12 col-md-4 col-lg-2"><strong>Statement:</strong><br>
      <a href="/monetarypolicy/files/monetary20260318a1.pdf">PDF</a></div>
  </div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>September</strong></div>
    <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">15-16</div>
    <div class="col-xs-12 col-md-4 col-lg-2"><strong>Statement:</strong><br>
      <a href="/monetarypolicy/files/monetary20260916a1.pdf">PDF</a></div>
    <div class="col-xs-12 col-md-4 col-lg-3"><a href="/monetarypolicy/fomcpressconf20260916.htm">Press Conference Transcript</a></div>
  </div>
</div>
<div class="panel panel-default"><div class="panel-heading"><h4><a id="45694">2027 FOMC Meetings</a></h4></div>
  <div class="row fomc-meeting">
    <div class="fomc-meeting__month col-xs-5 col-sm-3 col-md-2"><strong>January</strong></div>
    <div class="fomc-meeting__date col-xs-4 col-sm-9 col-md-10 col-lg-1">26-27</div>
    <div class="col-xs-12 col-md-4 col-lg-2"><strong>Statement:</strong><br>
      <a href="/monetarypolicy/files/monetary20270127a1.pdf">PDF</a></div>
  </div>
</div>
"""


def test_fred_release_dates_with_server_side_window(tmp_path: Path) -> None:
    """#83 §3A: realtime_start/end bound the window; rows carry the stable id + ET time."""
    client = _Client(
        fred_by_release={
            10: ["2026-08-12", "2026-09-11"],  # out-of-window date must be filtered by the API's own window
            50: ["2026-08-07"],
        }
    )
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider._fred_release_dates(10, "2026-08-07", "2026-08-30")

    url, params = client.calls[0]
    assert "api.stlouisfed.org/fred/release/dates" in url
    assert params["realtime_start"] == "2026-08-07" and params["realtime_end"] == "2026-08-30"
    assert params["release_id"] == 10 and params["api_key"] == "test-fred-key"
    assert rows == [
        {"id": "econ-fred-10-2026-08-12", "title": "Consumer Price Index", "date": "2026-08-12",
         "time_et": "08:30", "importance": "high", "country": "US", "source": "fred"}
    ]


def test_fomc_meeting_parse(tmp_path: Path) -> None:
    """#83 §3C: statement on the SECOND day at 14:00 ET; press-conf marker via link presence."""
    client = _Client(fred_by_release={}, fomc_html=FOMC_HTML)
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider._fomc_meetings("2026-01-01", "2026-12-31")

    by_id = {r["id"]: r for r in rows}
    # January 27-28 has a press-conf link → decision day 28.
    assert by_id["econ-fomc-2026-01-28"]["time_et"] == "14:00"
    assert by_id["econ-fomc-2026-01-28"]["title"] == "FOMC Meeting (press conference)"
    assert by_id["econ-fomc-2026-01-28"]["source"] == "fomc"
    # March 17-18 has no press-conf link.
    assert by_id["econ-fomc-2026-03-18"]["title"] == "FOMC Meeting"
    # September 15-16 → decision day 16.
    assert "econ-fomc-2026-09-16" in by_id
    # 2027 rows exist but fall outside the window → filtered.
    assert not any(r["date"].startswith("2027") for r in rows)


def test_get_economic_calendar_merges_and_sorts(tmp_path: Path) -> None:
    client = _Client(
        fred_by_release={
            10: ["2026-08-12", "2026-09-11"],
            192: ["2026-09-01"],  # JOLTS, medium, 10:00 ET
        },
        fomc_html=FOMC_HTML,
    )
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider.get_economic_calendar("2026-08-07", "2026-09-30")

    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)
    by_id = {r["id"]: r for r in rows}
    assert by_id["econ-fred-10-2026-08-12"]["importance"] == "high"
    assert by_id["econ-fred-192-2026-09-01"]["importance"] == "medium"
    assert by_id["econ-fred-192-2026-09-01"]["time_et"] == "10:00"
    assert by_id["econ-fomc-2026-09-16"]["source"] == "fomc"
    # 2027 FOMC and the out-of-window CPI date are excluded.
    assert all("2026-08-07" <= d <= "2026-09-30" for d in dates)


def test_allowlist_is_never_driven_by_bulk_releases(tmp_path: Path) -> None:
    """#83 trap: only allowlisted ids are ever fetched — 101 (FOMC press release) is NOT used."""
    assert 101 not in RELEASES
    assert set(RELEASES) == {10, 50, 54, 46, 53, 9, 192}


def test_missing_key_fails_fast(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.api_key = ""
    with pytest.raises(ProviderError, match="DATA_FRED_API_KEY"):
        provider._fred_release_dates(10, "2026-08-07", "2026-08-30")


def test_one_failing_release_does_not_discard_the_rest(tmp_path: Path) -> None:
    """#94 review: the calendar must not be empty because its most fragile source hiccupped —
    a single failing release keeps the rows already fetched from the others."""
    client = _Client(
        fred_by_release={10: ["2026-08-12"], 192: ["2026-09-01"]},
        failing_releases={10},
        fomc_html=FOMC_HTML,
    )
    provider = _provider(tmp_path)
    provider._client = client

    rows = provider.get_economic_calendar("2026-08-07", "2026-09-30")

    by_id = {r["id"]: r for r in rows}
    assert "econ-fred-10-2026-08-12" not in by_id  # the failing release contributes nothing
    assert by_id["econ-fred-192-2026-09-01"]["source"] == "fred"
    assert by_id["econ-fomc-2026-09-16"]["source"] == "fomc"


def test_all_sources_failed_raises(tmp_path: Path) -> None:
    client = _Client(fred_by_release={}, failing_releases=set(RELEASES), fomc_fails=True)
    provider = _provider(tmp_path)
    provider._client = client
    with pytest.raises(ProviderError, match="all sources failed"):
        provider.get_economic_calendar("2026-08-07", "2026-08-30")
