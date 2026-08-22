"""A-share coverage (#97, uses #85): CN symbol mapping, Tencent akshare backend, and the
quote/history decoupling that lets a cached quote survive a missing history."""

from __future__ import annotations

import sys
import time
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
        assert calls[0]["timeout"] == provider.timeout_seconds
        assert result.rows[-1]["close"] == pytest.approx(385.0)
        assert result.rows[0]["date"] == "2026-08-05"

    def test_history_timeout_is_enforced(self, tmp_path: Path, monkeypatch) -> None:
        from pipeline.providers.akshare_provider import AkshareProvider

        class _SlowAK:
            def stock_zh_a_hist_tx(self, **kwargs):
                time.sleep(0.05)
                return pd.DataFrame()

        monkeypatch.setitem(sys.modules, "akshare", _SlowAK())
        provider = AkshareProvider(Settings(_env_file=None, artifacts_dir=tmp_path))
        provider.timeout_seconds = 0.001

        with pytest.raises(ProviderError, match="timed out"):
            provider.get_history("603986.SH", period="1y")


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


class TestLastGoodReplay:
    def test_cache_replays_through_the_real_registry(self, tmp_path: Path) -> None:
        """#97 DoD 3/5: the last-good cache actually replays for a_share through the REAL
        registry path (not a mocked call) — a provider failure falls through to the cache
        and the #85 cross-check values come back (385.44 / 8.2636)."""
        import json

        from pipeline.providers.base import ProviderRegistry
        from pipeline.providers.yahoo import YahooAShareProvider
        from pipeline.schemas.envelope import SCHEMA_VERSION
        from pipeline.utils import now_utc

        registry = ProviderRegistry(Settings(_env_file=None, artifacts_dir=tmp_path))
        registry.cache_dir = tmp_path / "cache"
        registry.max_retries = 0
        registry.backoff_base = 0.0

        class _Down(YahooAShareProvider):
            def get_quote(self, symbol: str):
                raise ProviderError("yfinance_a_share down")

            def get_history(self, symbol: str, period: str = "1y"):
                raise ProviderError("yfinance_a_share down")

        registry.register("a_share", _Down(Settings(_env_file=None)))

        # Seed a valid last-good entry (schema_version present — the pre-#103 legacy file
        # on disk is quarantined, this is the format a current run writes).
        registry.cache_dir.mkdir(parents=True, exist_ok=True)
        (registry.cache_dir / "a_share__quote_603986.SH.json").write_text(
            json.dumps(
                {
                    "method": "get_quote",
                    "data": {
                        "symbol": "603986.SH", "price": 385.44, "change_1d": 8.2636,
                        "change_1w": None, "change_1m": None, "volume": None,
                        "source": "yahoo", "provider": "yfinance_a_share",
                        "updated_at": now_utc(), "is_proxy": False,
                    },
                    "fetched_at": now_utc(),
                    "provider": "yfinance_a_share",
                    "schema_version": SCHEMA_VERSION,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        out = registry.call("a_share", "get_quote", "quote_603986.SH", args=("603986.SH",))
        assert out["meta"]["from_cache"] is True
        assert out["meta"]["provider"] == "yfinance_a_share"
        assert out["result"].price == 385.44
        assert out["result"].change_1d == 8.2636  # the #85 cross-check values

    def test_legacy_entry_without_schema_version_is_quarantined(self, tmp_path: Path) -> None:
        """S-2 trust: a pre-#103 cache entry (no schema_version) is a miss and quarantined
        — that is why the real a_share__quote_603986.SH.json sits as .corrupt today; the
        next successful run re-seeds the cache in the current format."""
        import json

        from pipeline.providers.base import ProviderError, ProviderRegistry
        from pipeline.providers.yahoo import YahooAShareProvider

        registry = ProviderRegistry(Settings(_env_file=None, artifacts_dir=tmp_path))
        registry.cache_dir = tmp_path / "cache"
        registry.max_retries = 0
        registry.cache_dir.mkdir(parents=True, exist_ok=True)
        (registry.cache_dir / "a_share__quote_603986.SH.json").write_text(
            json.dumps({"method": "get_quote", "data": {"symbol": "603986.SH", "price": 385.44},
                        "fetched_at": "2026-08-05T19:26:09Z", "provider": "yfinance_a_share"}),
            encoding="utf-8",
        )

        class _Down(YahooAShareProvider):
            def get_quote(self, symbol: str):
                raise ProviderError("down")

        registry.register("a_share", _Down(Settings(_env_file=None)))
        with pytest.raises(ProviderError):
            registry.call("a_share", "get_quote", "quote_603986.SH", args=("603986.SH",))
        assert (registry.cache_dir / "a_share__quote_603986.SH.json.corrupt").exists()


def test_a_share_chain_has_two_rungs(tmp_path: Path) -> None:
    """#97 DoD: a second provider is registered for a_share — yfinance_a_share primary,
    akshare fallback (the domain previously had one provider, degradation was
    cache-or-nothing)."""
    from pipeline.providers import build_default_providers

    providers = [p for p in build_default_providers(Settings(_env_file=None)) if p.domain == "a_share"]
    assert [(p.name, p.priority) for p in providers] == [("yfinance_a_share", 1), ("akshare", 2)]
