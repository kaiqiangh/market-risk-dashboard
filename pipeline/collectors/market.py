"""Market collector (architecture §3.7 MarketCollector: quotes + crypto + A-shares + themes).

Produces: equities / crypto / sectors datasets + history (for indicator/risk use).
Any Provider failure → degradation chain → degraded, does not interrupt.
"""

from __future__ import annotations

from typing import Any

from pipeline.degrade import degraded_quality
from pipeline.indicators.technical import technical_snapshot
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import (
    CryptoAsset,
    CryptoDataset,
    CryptoEnvelope,
    EquitiesDataset,
    EquitiesEnvelope,
    EquityAsset,
    MemoryProxy,
    SectorItem,
    SectorsDataset,
    SectorsEnvelope,
)
from pipeline.settings import Settings
from pipeline.universe import AssetUniverse
from pipeline.utils import now_utc

# Breadth/trend benchmark indices (MVP proxies)
INDEX_HISTORIES = {"SPY": "1y", "IWM": "1y", "SOXX": "1y"}


class MarketCollector:
    def __init__(self, registry: ProviderRegistry, universe: AssetUniverse, settings: Settings | None = None) -> None:
        self.registry = registry
        self.universe = universe
        self.settings = settings or Settings()
        self.degraded: list[str] = []
        self.provider_status: dict[str, Any] = {}
        self.histories: dict[str, list[dict[str, Any]]] = {}
        self._domain_failures: dict[str, int] = {}
        self._domain_down: set[str] = set()

    # ---- Quotes (US + A-shares) ----

    def _fetch_equity(self, asset: Any) -> EquityAsset | None:
        domain = "quotes" if asset.market == "US" else "a_share"
        if domain in self._domain_down:
            # Domain confirmed down (e.g. akshare proxy blocked) → fast degrade, no per-symbol retry
            self.degraded.append(f"{asset.symbol}: {domain} domain down, skipped")
            return None
        try:
            quote_out = self.registry.call(domain, "get_quote", f"quote_{asset.symbol}", args=(asset.symbol,))
            hist_out = self.registry.call(domain, "get_history", f"hist_{asset.symbol}_1y", args=(asset.symbol, "1y"))
        except ProviderError as exc:
            self.degraded.append(f"{asset.symbol}: {exc}")
            self.provider_status.setdefault(domain, {})["error"] = str(exc)
            self._domain_failures[domain] = self._domain_failures.get(domain, 0) + 1
            if self._domain_failures[domain] >= 2:
                self._domain_down.add(domain)
            return None

        quote = quote_out["result"]
        rows = hist_out["result"].rows
        tech = technical_snapshot(rows)
        self.histories[asset.symbol] = rows
        return EquityAsset(
            symbol=asset.symbol,
            name=asset.name,
            name_zh=asset.name_zh,
            market="US" if asset.market == "US" else "CN",
            sector=asset.sector,
            theme=asset.theme,
            price=quote.price,
            currency="USD" if asset.market == "US" else "CNY",
            change_1d=quote.change_1d,
            change_1w=quote.change_1w,
            change_1m=quote.change_1m,
            change_ytd=None,
            volume=quote.volume,
            market_cap=None,
            ma50_distance_pct=tech["ma50_distance_pct"],
            ma200_distance_pct=tech["ma200_distance_pct"],
            rsi14=tech["rsi14"],
            percentile_5y=tech["percentile_5y"],
            source=quote.source,
            updated_at=quote.updated_at or now_utc(),
            is_proxy=quote.is_proxy,
        )

    def _collect_equities(self) -> EquitiesDataset:
        assets: list[EquityAsset] = []
        for asset in [*self.universe.us_equities, *self.universe.a_share_memory]:
            item = self._fetch_equity(asset)
            if item is not None:
                assets.append(item)
        return EquitiesDataset(assets=assets)

    # ---- Index history (breadth/trend) ----

    def _collect_index_histories(self) -> None:
        for symbol, period in INDEX_HISTORIES.items():
            try:
                out = self.registry.call("quotes", "get_history", f"hist_{symbol}_{period}", args=(symbol, period))
                self.histories[symbol] = out["result"].rows
            except ProviderError as exc:
                self.degraded.append(f"{symbol}: {exc}")

    # ---- Crypto ----

    def _collect_crypto(self) -> CryptoDataset:
        try:
            out = self.registry.call("crypto", "get_crypto_market", "crypto_market")
            data = out["result"]
            self.provider_status["crypto"] = out["meta"]
        except ProviderError as exc:
            self.degraded.append(f"crypto: {exc}")
            self.provider_status["crypto"] = {"degraded": True, "error": str(exc)}
            return CryptoDataset(assets=[], btc_dominance=None, stablecoin_mcap=None, market_cap_total=None, sentiment=None)

        assets = [
            CryptoAsset(**row)
            for row in data.get("assets", [])
            if row.get("price") is not None
        ]
        return CryptoDataset(
            assets=assets,
            btc_dominance=data.get("btc_dominance"),
            stablecoin_mcap=data.get("stablecoin_mcap"),
            market_cap_total=data.get("market_cap_total"),
            sentiment=data.get("sentiment"),
        )

    # ---- Sectors/themes ----

    def _collect_sectors(self, equities: EquitiesDataset) -> SectorsDataset:
        us = [a for a in equities.assets if a.market == "US"]
        cn = [a for a in equities.assets if a.market == "CN"]

        def _avg_change(assets: list[EquityAsset], key: str) -> float | None:
            values = [getattr(a, key) for a in assets if getattr(a, key) is not None]
            return round(sum(values) / len(values), 4) if values else None

        semis = [a for a in us if a.sector == "semis"]
        memory_assets = [a for a in us if "Memory" in a.theme] + cn
        auto = [a for a in us if a.sector == "auto"]

        sectors = [
            SectorItem(key="semis", label="Semiconductors", label_zh="半导体", change_1d=_avg_change(semis, "change_1d"), change_1w=_avg_change(semis, "change_1w"), change_1m=_avg_change(semis, "change_1m"), percentile_5y=None, updated_at=now_utc()),
            SectorItem(key="auto", label="Autos", label_zh="汽车", change_1d=_avg_change(auto, "change_1d"), change_1w=_avg_change(auto, "change_1w"), change_1m=_avg_change(auto, "change_1m"), percentile_5y=None, updated_at=now_utc()),
        ]
        themes = [
            SectorItem(key="memory", label="Memory", label_zh="存储", change_1d=_avg_change(memory_assets, "change_1d"), change_1w=_avg_change(memory_assets, "change_1w"), change_1m=_avg_change(memory_assets, "change_1m"), percentile_5y=None, updated_at=now_utc()),
            SectorItem(key="ai", label="AI / GPU", label_zh="AI/GPU", change_1d=_avg_change(semis, "change_1d"), change_1w=_avg_change(semis, "change_1w"), change_1m=_avg_change(semis, "change_1m"), percentile_5y=None, updated_at=now_utc()),
        ]

        mu = next((a for a in us if a.symbol == "MU"), None)
        memory = MemoryProxy(
            label="Memory proxy (MU + A-share memory makers)",
            label_zh="存储周期代理（美光 + A股存储）",
            change_1w=mu.change_1w if mu else _avg_change(memory_assets, "change_1w"),
            change_1m=mu.change_1m if mu else _avg_change(memory_assets, "change_1m"),
            note="DRAM/NAND spot prices are paywalled; MVP uses share prices as proxies (review P0-1)",
            updated_at=now_utc(),
        )
        return SectorsDataset(sectors=sectors, themes=themes, memory=memory)

    # ---- Summary ----

    def _quality(self) -> float:
        """Data quality degrades by the configured factor per failed domain (provider), not per failed asset."""
        failed = set(self._domain_down)
        for domain, count in self._domain_failures.items():
            if count > 0:
                failed.add(domain)
        crypto_status = self.provider_status.get("crypto")
        if isinstance(crypto_status, dict) and crypto_status.get("degraded"):
            failed.add("crypto")
        return degraded_quality(len(failed), settings=self.settings)

    def collect(self) -> dict[str, Any]:
        equities = self._collect_equities()
        self._collect_index_histories()
        crypto = self._collect_crypto()
        sectors = self._collect_sectors(equities)
        quality = self._quality()

        equity_env = EquitiesEnvelope(
            generated_at=now_utc(), schema_version="1.0.0",
            source=["yfinance", "akshare"], source_updated_at=now_utc(),
            freshness_status="degraded" if self.degraded else "fresh",
            data_quality=round(quality, 3), payload=equities,
        )
        crypto_env = CryptoEnvelope(
            generated_at=now_utc(), schema_version="1.0.0",
            source=["coingecko"], source_updated_at=now_utc(),
            freshness_status="degraded" if self.degraded else "fresh",
            data_quality=round(quality, 3), payload=crypto,
        )
        sectors_env = SectorsEnvelope(
            generated_at=now_utc(), schema_version="1.0.0",
            source=["yfinance"], source_updated_at=now_utc(),
            freshness_status="degraded" if self.degraded else "fresh",
            data_quality=round(quality, 3), payload=sectors,
        )
        return {
            "equities": equity_env,
            "crypto": crypto_env,
            "sectors": sectors_env,
            "histories": self.histories,
            "degraded": self.degraded,
            "provider_status": self.provider_status,
        }
