"""Commodities collection (#118): universe metals/oil flow through the quotes domain.

Covers the collector happy path, quote-failure degradation (drops the asset honestly), and
the envelope contract — the same shape as equities but without technicals.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.collectors.market import MarketCollector
from pipeline.providers.base import HistoryResult, ProviderError, QuoteResult
from pipeline.schemas.commodities import CommoditiesEnvelope
from pipeline.schemas.envelope import assemble_dataset
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse


class _FakeRegistry:
    def __init__(self, fail_symbols: set[str] | None = None) -> None:
        self.fail_symbols = fail_symbols or set()
        self.degraded_domains: set[str] = set()

    def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
        symbol = str(args[0])
        if method == "get_quote" and symbol not in self.fail_symbols:
            return {
                "result": QuoteResult(
                    symbol=symbol, price=2450.5, change_1d=0.8, change_1w=1.2,
                    change_1m=3.4, volume=0, source="yfinance", provider="yfinance",
                    updated_at="2026-08-06T10:00:00Z", is_proxy=False,
                ),
                "meta": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
            }
        raise ProviderError(f"{symbol}: boom")


def _collector(registry, tmp_path: Path) -> MarketCollector:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    universe = AssetUniverse.load(settings)
    return MarketCollector(registry, universe, settings)


class TestCommoditiesCollector:
    def test_governed_cross_asset_histories_are_fetched_once(self, tmp_path: Path) -> None:
        from pipeline.collectors.market import INDEX_HISTORIES

        class _HistoryRegistry(_FakeRegistry):
            def __init__(self) -> None:
                super().__init__()
                self.calls: list[tuple[str, str]] = []

            def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
                if method == "get_history":
                    symbol, period = args
                    self.calls.append((symbol, period))
                    return {
                        "result": HistoryResult(
                            symbol=symbol,
                            provider="yfinance",
                            rows=[{"date": "2026-08-05", "close": 100.0}, {"date": "2026-08-06", "close": 101.0}],
                            period=period,
                        ),
                        "meta": {"provider": "yfinance", "used_fallback": False, "from_cache": False},
                    }
                return super().call(domain, method, key, args, kwargs)

        registry = _HistoryRegistry()
        collector = _collector(registry, tmp_path)
        collector._collect_index_histories()

        assert set(registry.calls) == set(INDEX_HISTORIES.items())
        assert len(registry.calls) == len(INDEX_HISTORIES)
        assert {"XLY", "XLP", "HYG", "IEF"} <= collector.histories.keys()

    def test_index_history_failure_marks_quotes_degraded(self, tmp_path: Path) -> None:
        class _FailingHistoryRegistry(_FakeRegistry):
            def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
                if method == "get_history":
                    raise ProviderError(f"{args[0]}: history unavailable")
                return super().call(domain, method, key, args, kwargs)

        registry = _FailingHistoryRegistry()
        collector = _collector(registry, tmp_path)
        collector._collect_index_histories()

        assert "quotes" in registry.degraded_domains
        assert collector.provider_status["quotes"]["error"]

    def test_collects_universe_metals_and_oil(self, tmp_path: Path) -> None:
        """All universe.yaml metals+oil symbols publish assets (gold/silver/copper/oil)."""
        registry = _FakeRegistry()
        dataset = _collector(registry, tmp_path)._collect_commodities()
        symbols = {a.symbol for a in dataset.assets}
        assert {"GC=F", "SI=F", "HG=F", "CL=F"} <= symbols
        gold = next(a for a in dataset.assets if a.symbol == "GC=F")
        assert gold.name == "Gold"
        assert gold.name_zh == "黄金"
        assert gold.price == 2450.5
        assert gold.change_1d == 0.8 and gold.change_1m == 3.4

    def test_quote_failure_drops_the_asset_and_degrades(self, tmp_path: Path) -> None:
        """A failed commodity quote drops that asset (honest) and records the degradation."""
        registry = _FakeRegistry(fail_symbols={"HG=F"})
        collector = _collector(registry, tmp_path)
        dataset = collector._collect_commodities()
        symbols = {a.symbol for a in dataset.assets}
        assert "HG=F" not in symbols
        assert any("HG=F" in d for d in collector.degraded)
        assert collector.provider_status.get("quotes", {}).get("error")


class TestCommoditiesEnvelope:
    def test_envelope_assembles_and_validates(self, tmp_path: Path) -> None:
        """commodities.json assembles through the single path (freshness + provenance)."""
        from pipeline.schemas.registry import require

        registry = _FakeRegistry()
        dataset = _collector(registry, tmp_path)._collect_commodities()
        assembled = assemble_dataset(
            require("commodities").model,
            dataset,
            dataset="commodities",
            degraded=False,
            provider="yfinance",
            used_fallback=False,
            from_cache=False,
            data_quality=1.0,
            row_count=len(dataset.assets),
        )
        assert isinstance(assembled.envelope, CommoditiesEnvelope)
        assert assembled.envelope.payload.assets
        assert assembled.envelope.freshness_status in ("fresh", "delayed", "stale")
        assert assembled.envelope.provenance.provider == "yfinance"
