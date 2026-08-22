"""Macro coverage (#96, uses #84): 27-series roster, units transforms, frequency-aware
change/status, memoised bounded FRED fetches, volatility group, history bundles + manifest."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from pipeline.collectors.macro import (
    DEFAULT_SERIES,
    SERIES_GROUPS,
    MacroCollector,
    _group_of,
    _series_status,
)
from pipeline.providers.base import ProviderError
from pipeline.providers.fred import SERIES_CATALOG
from pipeline.settings import Settings
from pipeline.storage.writer import StorageWriter


def _rows(days: int = 60, start_value: float = 100.0) -> list[dict[str, Any]]:
    """Ascending daily rows ending today."""
    out = []
    for i in range(days):
        d = (date.today() - timedelta(days=days - 1 - i)).isoformat()
        out.append({"date": d, "value": round(start_value + i * 1.0, 4)})
    return out


class _FakeRegistry:
    def __init__(self, rows_by_series: dict[str, list[dict]], fail: set[str] | None = None) -> None:
        self._rows = rows_by_series
        self._fail = fail or set()
        self.calls: list[tuple[str, str, dict]] = []
        self.degraded_domains: set[str] = set()

    def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
        kwargs = kwargs or {}
        if domain == "fedwatch":
            self.calls.append((domain, method, key, kwargs))
            code = str(args[0][0])
            return {
                "result": {code: 94.75 if code == "ZQU26.CBT" else 94.70},
                "meta": {"provider": "fedwatch", "used_fallback": False, "from_cache": False, "degraded": False},
            }
        series_id = str(args[0])
        self.calls.append((domain, method, series_id, kwargs))
        if series_id in self._fail:
            raise ProviderError(f"FRED {series_id}: HTTP 500")
        return {"result": self._rows.get(series_id, []), "meta": {"provider": "fred", "used_fallback": False, "from_cache": False}}


def _all_series_rows() -> dict[str, list[dict]]:
    return {sid: _rows() for sid in DEFAULT_SERIES}


def _collector(registry, tmp_path: Path) -> MacroCollector:
    return MacroCollector(
        registry,
        Settings(_env_file=None, artifacts_dir=tmp_path, data_dir=tmp_path / "data"),
    )


class TestRoster:
    def test_default_series_is_derived_from_groups(self) -> None:
        """#84 §0 root cause: two lists drifted apart. One list now — the fetch loop
        iterates the grouping table, so the mismatch is structurally impossible."""
        assert DEFAULT_SERIES == [s for group in SERIES_GROUPS.values() for s in group]
        assert len(DEFAULT_SERIES) == 27
        assert len(set(DEFAULT_SERIES)) == 27  # no duplicates

    def test_roster_is_complete_against_the_catalog(self) -> None:
        """Every catalog series except the EFFR anchor is in the roster, and the roster
        contains no dead ids (NAPM/MOVE/GOLDPMGBD228NLBM were FRED 400s, #84 §6c)."""
        roster = set(DEFAULT_SERIES)
        assert roster == set(SERIES_CATALOG) - {"EFFR"}
        assert "NAPM" not in roster and "MOVE" not in roster

    def test_groups_match_84(self) -> None:
        assert SERIES_GROUPS["volatility"] == ["VIXCLS"]  # VIX out of rates
        assert "T10YIE" in SERIES_GROUPS["inflation"]  # moved out of rates
        assert "T10YIE" not in SERIES_GROUPS["rates"]
        assert "DFF" in SERIES_GROUPS["rates"]
        assert len(SERIES_GROUPS["inflation"]) == 5
        assert len(SERIES_GROUPS["labor"]) == 5
        assert len(SERIES_GROUPS["liquidity"]) == 5
        assert len(SERIES_GROUPS["fx"]) == 5


class TestCollector:
    def test_all_groups_populated_with_volatility(self, tmp_path: Path, monkeypatch) -> None:
        registry = _FakeRegistry(_all_series_rows())
        collector = _collector(registry, tmp_path)
        monkeypatch.setattr("pipeline.collectors.macro.MacroCollector._collect_fedwatch", lambda self: None)
        dataset = collector.collect()[0]

        assert len(dataset.rates) == 4
        assert len(dataset.credit) == 2
        assert [i.key for i in dataset.volatility] == ["vixcls"]
        assert len(dataset.inflation) == 5
        assert len(dataset.labor) == 5
        assert len(dataset.liquidity) == 5
        assert len(dataset.fx) == 5
        assert "t10yie" in [i.key for i in dataset.inflation]

    def test_units_transform_and_5y_window_are_passed(self, tmp_path: Path, monkeypatch) -> None:
        registry = _FakeRegistry(_all_series_rows())
        collector = _collector(registry, tmp_path)
        monkeypatch.setattr("pipeline.collectors.macro.MacroCollector._collect_fedwatch", lambda self: None)
        collector.collect()

        by_id = {sid: kwargs for _, _, sid, kwargs in registry.calls}
        # CPI is an index at ~330 → server-side YoY transform (units=pc1).
        assert by_id["CPIAUCSL"]["units"] == "pc1"
        assert by_id["PCEPILFE"]["units"] == "pc1"
        # PAYEMS is total employed → monthly change (units=chg).
        assert by_id["PAYEMS"]["units"] == "chg"
        # Rates pass no transform.
        assert by_id["DGS10"]["units"] == "lin"
        # #84 §4: every request bounded to the 5y window. The collector anchors on the UTC
        # date (not the runner-local one) — the assertion must match or it flakes on TZ.
        expected_start = (datetime.now(timezone.utc).date() - timedelta(days=5 * 365)).isoformat()
        for sid, kwargs in by_id.items():
            assert kwargs["start"] == expected_start, sid

    def test_dff_is_fetched_once(self, tmp_path: Path, monkeypatch) -> None:
        """#84 §4: DFF used to be fetched twice per run (roster + FedWatch anchor)."""
        registry = _FakeRegistry(_all_series_rows())
        collector = _collector(registry, tmp_path)
        monkeypatch.setattr("pipeline.collectors.macro.MacroCollector._collect_fedwatch", lambda self: None)
        collector.collect()
        assert sum(1 for _, _, sid, _ in registry.calls if sid == "DFF") == 1

    def test_fedwatch_uses_registry_and_generates_codes_once(self, tmp_path: Path, monkeypatch) -> None:
        registry = _FakeRegistry(_all_series_rows())
        collector = _collector(registry, tmp_path)
        codes_calls: list[bool] = []
        monkeypatch.setattr(
            "pipeline.collectors.macro.next_contract_codes",
            lambda: codes_calls.append(True) or ["ZQU26.CBT", "ZQZ26.CBT"],
        )

        snapshot = collector._collect_fedwatch()

        assert snapshot is not None
        assert len(codes_calls) == 1
        assert any(domain == "fedwatch" and method == "get_contract_prices" for domain, method, *_ in registry.calls)
        assert sum(1 for domain, _, _, _ in registry.calls if domain == "fedwatch") == 2

    def test_change_1m_is_frequency_aware(self, tmp_path: Path, monkeypatch) -> None:
        """#84 §6a: 21 rows is one month only for daily series; a monthly series must
        use a 1-row lookback or the "1m" label lies by 21×."""
        daily = _rows(60)
        monthly = _rows(60, start_value=200.0)[::30]  # 2 monthly points
        registry = _FakeRegistry({**{sid: daily for sid in DEFAULT_SERIES}, "CPIAUCSL": monthly})
        collector = _collector(registry, tmp_path)
        monkeypatch.setattr("pipeline.collectors.macro.MacroCollector._collect_fedwatch", lambda self: None)
        dataset = collector.collect()[0]

        dgs10 = next(i for i in dataset.rates if i.key == "dgs10")
        assert dgs10.change_1m == pytest.approx(daily[-1]["value"] - daily[-22]["value"], abs=1e-6)  # 21 rows back
        cpi = next(i for i in dataset.inflation if i.key == "cpiaucsl")
        assert cpi.change_1m == pytest.approx(monthly[-1]["value"] - monthly[-2]["value"], abs=1e-6)  # 1 row back

    def test_status_is_frequency_aware(self) -> None:
        """#84 §6b: a row count is not freshness. A monthly series unchanged for 30 days
        is fresh; a daily series 10 days behind is stale."""
        today = date.today().isoformat()
        assert _series_status(today, "monthly") == "fresh"
        assert _series_status((date.today() - timedelta(days=30)).isoformat(), "monthly") == "fresh"
        assert _series_status((date.today() - timedelta(days=10)).isoformat(), "daily") == "stale"
        assert _series_status((date.today() - timedelta(days=2)).isoformat(), "weekly") == "fresh"

    def test_group_of_is_loud_on_unmapped(self) -> None:
        """#84 §5: an unmapped series used to misfile under "rates" silently."""
        with pytest.raises(KeyError):
            _group_of("SOMETHING_NEW")


class TestHistory:
    def test_write_macro_history_two_layers(self, tmp_path: Path) -> None:
        from pipeline.storage.macro_history import write_macro_history

        writer = StorageWriter(tmp_path)
        rows_by_series = {sid.lower(): _rows(100) for sid in DEFAULT_SERIES}
        counts = write_macro_history(writer, rows_by_series, SERIES_GROUPS)

        # Layer 1: per-series append-only archive.
        assert counts["archive"] == 27
        archive = tmp_path / "history" / "macro" / "DGS10" / "daily.json"
        assert archive.exists()
        assert len(writer.read_history("macro/DGS10", "daily")) == 100

        # Layer 2: per-group 30d/90d bundles (sparse column-oriented) + manifest.
        assert counts["bundles"] == 14
        import json

        bundle = json.loads((tmp_path / "history" / "macro" / "fx.30d.json").read_text(encoding="utf-8"))
        assert set(bundle) == set(SERIES_GROUPS["fx"])
        for _series, cols in bundle.items():
            assert len(cols["d"]) == 30 and len(cols["v"]) == 30

        manifest = json.loads((tmp_path / "history" / "macro" / "index.json").read_text(encoding="utf-8"))
        assert set(manifest["series"]) == set(DEFAULT_SERIES)
        dgs10 = manifest["series"]["DGS10"]
        assert dgs10["group"] == "rates" and dgs10["frequency"] == "daily"
        assert dgs10["last_observation"] == rows_by_series["dgs10"][-1]["date"]
        assert dgs10["next_expected_release"] > dgs10["last_observation"]
        assert manifest["series"]["WALCL"]["scale"] == "mil_usd"
        assert manifest["series"]["RRPONTSYD"]["scale"] == "bil_usd"

    def test_internal_anchor_does_not_leak_into_history(self, tmp_path: Path) -> None:
        """#96 review: when DFF fails and the EFFR anchor succeeds, series_history gains
        `effr` — an internal anchor, not a published series. It must not write a
        None-group bundle (was history/macro/None.30d.json) nor appear in the manifest."""
        import json

        from pipeline.storage.macro_history import write_macro_history

        writer = StorageWriter(tmp_path)
        rows_by_series = {sid.lower(): _rows(100) for sid in DEFAULT_SERIES}
        rows_by_series["effr"] = _rows(30)  # FedWatch fallback anchor
        counts = write_macro_history(writer, rows_by_series, SERIES_GROUPS)

        assert counts["archive"] == 27  # EFFR excluded
        assert not (tmp_path / "history" / "macro" / "None.30d.json").exists()
        assert not (tmp_path / "history" / "macro" / "EFFR" / "daily.json").exists()
        manifest = json.loads((tmp_path / "history" / "macro" / "index.json").read_text(encoding="utf-8"))
        assert "EFFR" not in manifest["series"]
