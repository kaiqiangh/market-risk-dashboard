"""A-share coverage (#97, uses #85): CN symbol mapping, Tencent akshare backend, and the
quote/history decoupling that lets a cached quote survive a missing history."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from pipeline.collectors.market import MarketCollector
from pipeline.providers.base import ProviderError, QuoteResult
from pipeline.providers.yahoo import YahooAShareProvider, map_cn_symbol
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse


class TestSymbolMapping:
    def test_shanghai_maps_to_ss(self) -> None:
        """603986.SH → 603986.SS (Yahoo's suffix for Shanghai; the .SZ-half looks identical
        and a mapper spot-checked only on Shenzhen silently breaks Shanghai — #85)."""
        assert map_cn_symbol("603986.SH") == "603986.SS"
        assert map_cn_symbol("688525.SH") == "688525.SS"  # STAR board
        assert map_cn_symbol("600584.SH") == "600584.SS"

    def test_shenzhen_and_us_pass_through(self) -> None:
        assert map_cn_symbol("301308.SZ") == "301308.SZ"
        assert map_cn_symbol("000021.SZ") == "000021.SZ"
        assert map_cn_symbol("NVDA") == "NVDA"
        assert map_cn_symbol("SPY") == "SPY"


class TestYahooAShareProvider:
    def test_registered_identity_and_mapper(self) -> None:
        assert YahooAShareProvider.name == "yfinance_a_share"
        assert YahooAShareProvider.domain == "a_share"
        assert YahooAShareProvider._symbol_mapper("603986.SH") == "603986.SS"


class TestAkshareTencentBackend:
    def test_history_uses_stock_zh_a_hist_tx(self, tmp_path: Path, monkeypatch) -> None:
        """#85 fix: the Eastmoney history tier (stock_zh_a_hist → push2his) is geo-blocked
        from this host; the Tencent backend answers. The provider must call it with the
        Tencent symbol form (sh603986)."""
        from pipeline.providers.akshare_provider import AkshareProvider

        calls: list[dict[str, Any]] = []

        class _FakeAK:
            def stock_zh_a_hist_tx(self, **kwargs):
                calls.append(kwargs)
                return pd.DataFrame(
                    {
                        "日期": ["2026-08-05", "2026-08-06"],
                        "开盘": [358.0, 385.0],
                        "最高": [390.0, 386.0],
                        "最低": [358.0, 383.0],
                        "收盘": [385.44, 385.0],
                        "成交量": [12345, 13000],
                    }
                )

        monkeypatch.setitem(sys.modules, "akshare", _FakeAK())
        provider = AkshareProvider(Settings(_env_file=None, artifacts_dir=tmp_path))
        result = provider.get_history("603986.SH", period="1y")

        assert calls[0]["symbol"] == "sh603986"
        assert calls[0]["adjust"] == "qfq"
        assert result.rows[-1]["close"] == pytest.approx(385.0)
        assert result.rows[0]["date"] == "2026-08-05"


class _FakeRegistry:
    def __init__(self, quote_ok: bool, history_ok: bool) -> None:
        self._quote_ok = quote_ok
        self._history_ok = history_ok
        self.degraded_domains: set[str] = set()

    def call(self, domain: str, method: str, key: str, args=(), kwargs=None):
        if method == "get_quote" and self._quote_ok:
            return {
                "result": QuoteResult(
                    symbol=str(args[0]), price=385.0, change_1d=0.5, change_1w=1.2,
                    change_1m=4.0, volume=1000, source="yahoo", provider="yfinance_a_share",
                    updated_at="2026-08-06T10:00:00Z", is_proxy=False,
                ),
                "meta": {"provider": "yfinance_a_share", "used_fallback": False, "from_cache": True},
            }
        if method == "get_history" and self._history_ok:
            return {"result": SimpleNamespace(rows=[{"date": "2026-08-05", "close": 385.44}]), "meta": {"provider": "yfinance_a_share"}}
        raise ProviderError("boom")


def _collector(registry, tmp_path: Path) -> MarketCollector:
    settings = Settings(_env_file=None, artifacts_dir=tmp_path)
    universe = AssetUniverse.load(settings)
    return MarketCollector(registry, universe, settings)


def _asset(symbol: str = "603986.SH") -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, name="GigaDevice", name_zh="兆易创新", market="CN", sector="semis")


class TestQuoteHistoryDecoupling:
    def test_cached_quote_survives_missing_history(self, tmp_path: Path) -> None:
        """#85 defect 2: quote (from cache) + failed history used to drop the symbol even
        though the price was recovered. Now the asset publishes with honest None technicals."""
        registry = _FakeRegistry(quote_ok=True, history_ok=False)
        asset_out = _collector(registry, tmp_path)._fetch_equity(_asset())

        item, domain, degraded, outcomes, status_error, rows = asset_out
        assert item is not None
        assert item.symbol == "603986.SH"
        assert item.price == 385.0
        assert item.ma50_distance_pct is None and item.percentile_1y is None
        assert item.source == "yahoo"  # the data source, not the answering provider name
        assert any("history unavailable" in d for d in degraded)
        assert status_error is not None

    def test_quote_failure_still_drops_the_symbol(self, tmp_path: Path) -> None:
        registry = _FakeRegistry(quote_ok=False, history_ok=True)
        item, domain, degraded, outcomes, status_error, rows = _collector(registry, tmp_path)._fetch_equity(_asset())
        assert item is None
        assert any("boom" in d for d in degraded)


def test_a_share_chain_has_two_rungs(tmp_path: Path) -> None:
    """#97 DoD: a second provider is registered for a_share — yfinance_a_share primary,
    akshare fallback (the domain previously had one provider, degradation was
    cache-or-nothing)."""
    from pipeline.providers import build_default_providers

    providers = [p for p in build_default_providers(Settings(_env_file=None)) if p.domain == "a_share"]
    assert [(p.name, p.priority) for p in providers] == [("yfinance_a_share", 1), ("akshare", 2)]
