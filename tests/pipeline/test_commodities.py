"""Commodities collection (#118): universe metals/oil flow through the quotes domain.

Covers the collector happy path, quote-failure degradation (drops the asset honestly), and
the envelope contract — the same shape as equities but without technicals.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.collectors.market import MarketCollector
from pipeline.providers.base import ProviderError, QuoteResult
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
