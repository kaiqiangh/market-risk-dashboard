"""Market collector (architecture §3.7 MarketCollector: quotes + crypto + A-shares + themes).

Produces: equities / crypto / sectors datasets + history (for indicator/risk use).
Any Provider failure → degradation chain → degraded, does not interrupt.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

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



class _EquityFetch(NamedTuple):
    """One equity's fetch result, merged by the caller in a single thread (#103/P-1)."""

    asset: EquityAsset | None
    domain: str
    degraded: list[str]
    outcomes: dict[str, dict[str, Any]]
    status_error: str | None
    rows: list[dict[str, Any]]


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
            return _EquityFetch(None, domain, degraded, outcomes, status_error, [])

        quote = quote_out["result"]
        rows = hist_out["result"].rows
        tech = technical_snapshot(rows)
        return _EquityFetch(
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
            """Build one SECTOR row from a themes.yaml definition (C-1/#102).

            Sectors (semis/auto) aggregate the collected equity cards; the 20 THEMES use the
            series machinery in :meth:`_collect_themes` instead (#93).
            """
            assets = [by_symbol[c.symbol] for c in theme.constituents if c.symbol in by_symbol]
            return SectorItem(
                key=key,
                change_1d=_avg_change(assets, "change_1d"),
                change_1w=_avg_change(assets, "change_1w"),
                change_1m=_avg_change(assets, "change_1m"),
                percentile_1y=None,
                percentile_1y_obs=0,
                constituents=[c.symbol for c in theme.constituents],
                updated_at=now_utc(),
            )

        sectors = [_row(key, theme) for key, theme in self.themes.sectors.items()]
        themes = self._collect_themes()

        # Memory cycle proxy (review P0-1): kept as its own object because the frontend
        # renders it as a single prose card; its numbers now come from the memory THEME
        # series (the proxy's change_1w/1m are the theme basket's, #93 supersedes the block).
        memory_series = next((t for t in themes if t.key == "memory"), None)
        memory = MemoryProxy(
            label="Memory cycle proxy (themes: memory basket)",
            label_zh="存储周期代理（主题：存储篮子）",
            change_1w=memory_series.change_1w if memory_series else None,
            change_1m=memory_series.change_1m if memory_series else None,
            note="DRAM/NAND spot prices are paywalled; the memory theme series proxies the cycle (#93 supersedes the MU-only proxy)",
            updated_at=now_utc(),
        )
        return SectorsDataset(sectors=sectors, themes=themes, memory=memory)

    def _collect_themes(self) -> list[SectorItem]:
        """Build the 20 theme rows from their SERIES (#93/#86 §4).

        An ETF-proxied theme publishes the ETF's own 1y series (one fetch; SOXX is already
        in INDEX_HISTORIES). A basket theme chains an equal-weight daily-return index from its
        constituents' 1y histories (A-share members are skipped: akshare's historical tier is
        blocked from this host per #85 — they contribute nothing until #97). Card numbers and
        ``percentile_1y`` both come from that one series, so they provably describe the same
        object.
        """
        from pipeline.indicators.themes import (
            chain_equal_weight_daily,
            changes_from_closes,
            percentile_of_trailing_return,
        )

        out: list[SectorItem] = []
        for key, theme in self.themes.themes.items():
            constituents = [c.symbol for c in theme.constituents]
            rows = self._theme_series(theme)
            item = SectorItem(key=key, constituents=constituents, updated_at=now_utc())
            closes = [r["close"] for r in rows if r.get("close") is not None]
            if len(closes) >= 2:
                item.change_1d, item.change_1w, item.change_1m = changes_from_closes(closes)
                percentile_cfg = theme.percentile or self.themes.percentile
                if percentile_cfg is not None:
                    percentile, obs = percentile_of_trailing_return(
                        closes,
                        window=percentile_cfg.window_sessions,
                        lookback=percentile_cfg.lookback_sessions,
                        min_observations=percentile_cfg.min_observations,
                    )
                    item.percentile_1y = percentile
                    item.percentile_1y_obs = obs
            out.append(item)

        # #86 §1 / D-1 regression: no two themes may publish identical series. The old
        # `ai` row was byte-identical to `semis`; a repeat of that is a hard fail.
        seen: dict[tuple, str] = {}
        for item in out:
            signature = (item.change_1d, item.change_1w, item.change_1m)
            if signature in seen and signature != (None, None, None):
                raise RuntimeError(
                    f"themes {seen[signature]!r} and {item.key!r} publish identical "
                    f"series {signature} (D-1 guard, #93)"
                )
            seen[signature] = item.key
        return out

    def _theme_series(self, theme: Any) -> list[dict[str, Any]]:
        """The 1y close series behind one theme (#93): the ETF's own series, or the
        equal-weight basket chained from constituent histories."""
        from pipeline.indicators.themes import chain_equal_weight_daily

        if theme.proxy is not None and theme.proxy.kind == "etf":
            return self._series_rows(theme.proxy.symbol)
        series_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for constituent in theme.constituents:
            if constituent.symbol.endswith((".SH", ".SZ")):
                continue  # #85: akshare's historical kline tier is blocked — no fake series
            rows = self._series_rows(constituent.symbol)
            if rows and len(rows) >= 2:
                series_by_symbol[constituent.symbol] = rows
        if not series_by_symbol:
            return []
        return chain_equal_weight_daily(series_by_symbol)

    def _series_rows(self, symbol: str) -> list[dict[str, Any]]:
        """1y OHLCV rows for a symbol, reusing whatever the run already fetched (#93 P-1)."""
        if symbol in self.histories:
            return self.histories[symbol]
        try:
            out = self.registry.call("quotes", "get_history", f"hist_{symbol}_1y", args=(symbol, "1y"))
            rows = out["result"].rows
            self.histories[symbol] = rows
            self._record_outcome("quotes", out["meta"])
            return rows
        except ProviderError:
            return []

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
