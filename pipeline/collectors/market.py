"""Market collector (architecture §3.7 MarketCollector: quotes + crypto + A-shares + themes).

Produces: equities / crypto / sectors datasets + history (for indicator/risk use).
Any Provider failure → degradation chain → degraded, does not interrupt.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.degrade import degraded_quality
from pipeline.indicators.technical import technical_snapshot
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import (
    CryptoAsset,
    CryptoDataset,
    EquitiesDataset,
    EquityAsset,
    MemoryProxy,
    SectorItem,
    SectorsDataset,
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
        # #102 (C-1): the sector/theme taxonomy lives in config/themes.yaml, not in this
        # module. Loading it validates every constituent resolves in universe.yaml and
        # raises ConfigError before any provider is constructed. Labels are nowhere here —
        # the frontend renders t(themes.<key>).
        self.themes = self.settings.load_themes_config()
        self.operations = self.settings.load_sources_config().operations
        # theme membership, reversed: symbol → theme keys, to populate EquityAsset.theme
        # (the payload keeps the field; universe.yaml no longer carries theme tags, D-8).
        self._symbol_to_themes: dict[str, list[str]] = {}
        for section in ("sectors", "themes"):
            for key, theme in getattr(self.themes, section).items():
                for constituent in theme.constituents:
                    self._symbol_to_themes.setdefault(constituent.symbol, []).append(key)
        self.degraded: list[str] = []
        self.provider_status: dict[str, Any] = {}
        self.histories: dict[str, list[dict[str, Any]]] = {}
        #: Domain → provider outcome of the most recent successful call (#65).
        self._provider_outcomes: dict[str, dict[str, Any]] = {}
        # #103/P-1: collection runs in a bounded thread pool; the per-(provider, host)
        # circuit breaker lives in the registry (threshold 3 consecutive transient
        # failures → fast-degrade, fallback/cache still answer). The collector's own
        # `_domain_failures`/`_domain_down` breaker is gone.

    def _record_outcome(self, domain: str, meta: dict[str, Any]) -> None:
        """Remember which provider answered a successful `registry.call` for `domain` (#65)."""
        self._provider_outcomes[domain] = meta

    def _provider_for(self, domain: str) -> dict[str, Any]:
        """The provenance for `domain`: the answering provider, or last-good, or unavailable."""
        outcome = self._provider_outcomes.get(domain) or self.registry.resolved_provider(domain)
        if outcome is not None:
            return {
                "provider": str(outcome.get("provider", "unavailable")),
                "used_fallback": bool(outcome.get("used_fallback", False)),
                "from_cache": bool(outcome.get("from_cache", False)),
            }
        return {"provider": "unavailable", "used_fallback": False, "from_cache": False}

    # ---- Quotes (US + A-shares) ----

    def _fetch_equity(
        self, asset: Any
    ) -> tuple[EquityAsset | None, str, list[str], dict[str, dict[str, Any]], str | None, list[dict[str, Any]]]:
        """Fetch one equity inside the thread pool (#103/P-1).

        Returns ``(asset, domain, degraded_msgs, provider_outcomes, status_error, rows)`` so
        the caller merges shared collector state in a single thread — the workers never touch
        ``self.degraded``/``self.provider_status``/``self.histories`` directly.
        """
        domain = "quotes" if asset.market == "US" else "a_share"
        degraded: list[str] = []
        outcomes: dict[str, dict[str, Any]] = {}
        status_error: str | None = None
        try:
            quote_out = self.registry.call(domain, "get_quote", f"quote_{asset.symbol}", args=(asset.symbol,))
            hist_out = self.registry.call(domain, "get_history", f"hist_{asset.symbol}_1y", args=(asset.symbol, "1y"))
            outcomes[domain] = quote_out["meta"]
        except ProviderError as exc:
            degraded.append(f"{asset.symbol}: {exc}")
            status_error = str(exc)
            return None, domain, degraded, outcomes, status_error, []

        quote = quote_out["result"]
        rows = hist_out["result"].rows
        tech = technical_snapshot(rows)
        return (
            EquityAsset(
                symbol=asset.symbol,
                name=asset.name,
                name_zh=asset.name_zh,
                market="US" if asset.market == "US" else "CN",
                sector=asset.sector,
                theme=list(self._symbol_to_themes.get(asset.symbol, [])),
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
                percentile_1y=tech["percentile_1y"],
                percentile_1y_obs=tech["percentile_1y_obs"],
                source=quote.source,
                updated_at=quote.updated_at or now_utc(),
                is_proxy=quote.is_proxy,
            ),
            domain,
            degraded,
            outcomes,
            status_error,
            rows,
        )

    def _collect_equities(self) -> EquitiesDataset:
        assets: list[EquityAsset] = []
        targets = [*self.universe.us_equities, *self.universe.a_share_memory]
        # #103/P-1: bounded thread pool; the registry's per-host limiter serializes calls to
        # the same host, so parallelism is bought per host and paced by config.
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
            results = list(pool.map(self._fetch_equity, targets))
        for item, domain, degraded, outcomes, status_error, rows in results:
            if item is not None:
                assets.append(item)
                self.histories[item.symbol] = rows
            self.degraded.extend(degraded)
            self._provider_outcomes.update(outcomes)
            if status_error:
                self.provider_status.setdefault(domain, {})["error"] = status_error
        return EquitiesDataset(assets=assets)

    # ---- Index history (breadth/trend) ----

    def _collect_index_histories(self) -> None:
        for symbol, period in INDEX_HISTORIES.items():
            try:
                out = self.registry.call("quotes", "get_history", f"hist_{symbol}_{period}", args=(symbol, period))
                self._record_outcome("quotes", out["meta"])
                self.histories[symbol] = out["result"].rows
            except ProviderError as exc:
                self.degraded.append(f"{symbol}: {exc}")

    # ---- Crypto ----

    def _collect_crypto(self) -> CryptoDataset:
        try:
            out = self.registry.call("crypto", "get_crypto_market", "crypto_market")
            data = out["result"]
            self.provider_status["crypto"] = out["meta"]
            self._record_outcome("crypto", out["meta"])
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
        by_symbol = {a.symbol: a for a in equities.assets}

        def _avg_change(assets: list[EquityAsset], key: str) -> float | None:
            values = [getattr(a, key) for a in assets if getattr(a, key) is not None]
            return round(sum(values) / len(values), 4) if values else None

        def _row(key: str, theme: Any) -> SectorItem:
            """Build one SectorItem from a themes.yaml definition (C-1/#102).

            Constituents are resolved against the assets that actually collected — a symbol
            whose fetch failed simply does not contribute, which is what the old sector/
            theme filter did implicitly over the collected asset list.
            """
            assets = [by_symbol[c.symbol] for c in theme.constituents if c.symbol in by_symbol]
            return SectorItem(
                key=key,
                change_1d=_avg_change(assets, "change_1d"),
                change_1w=_avg_change(assets, "change_1w"),
                change_1m=_avg_change(assets, "change_1m"),
                percentile_1y=None,
                percentile_1y_obs=0,
                updated_at=now_utc(),
            )

        sectors = [
            _row(key, theme) for key, theme in self.themes.sectors.items()
        ]
        themes = [
            _row(key, theme) for key, theme in self.themes.themes.items()
        ]

        # Memory cycle proxy (review P0-1): Micron + A-share memory makers — the same
        # membership as themes.yaml:themes.memory, which the memory theme row above is
        # built from. Kept as its own object because the frontend renders it as a single
        # prose proxy card, not a numbered row.
        memory_assets = [
            by_symbol[c.symbol] for c in self.themes.themes["memory"].constituents if c.symbol in by_symbol
        ]
        mu = next((a for a in memory_assets if a.symbol == "MU"), None)
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
        """Data quality degrades by the configured factor per degraded domain (#65).

        `ProviderRegistry.degraded_domains` is the reader: every domain that fell back or
        replayed from cache lowers published quality, compounding with the factor.
        """
        return degraded_quality(len(self.registry.degraded_domains), settings=self.settings)

    def collect(self) -> dict[str, Any]:
        equities = self._collect_equities()
        self._collect_index_histories()
        crypto = self._collect_crypto()
        sectors = self._collect_sectors(equities)
        quality = self._quality()

        # #64/#65: collectors return payloads + provider outcome; the caller (run.py) assembles
        # the envelope through the single assembly path and finalizes freshness + provenance.
        return {
            "equities": equities,
            "crypto": crypto,
            "sectors": sectors,
            "histories": self.histories,
            "degraded": self.degraded,
            "provider_status": self.provider_status,
            "data_quality": round(quality, 3),
            "providers": {
                "equities": self._provider_for("quotes") or self._provider_for("a_share"),
                "crypto": self._provider_for("crypto"),
                "sectors": self._provider_for("quotes"),
            },
        }
