"""Market collector (architecture §3.7 MarketCollector: quotes + crypto + A-shares + themes).

Produces: equities / crypto / sectors datasets + history (for indicator/risk use).
Any Provider failure → degradation chain → degraded, does not interrupt.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

from pipeline.indicators.technical import technical_snapshot
from pipeline.indicators.themes import changes_from_closes, percentile_of_trailing_return
from pipeline.metadata import latest_row_timestamp, oldest_source_timestamp, quality_for_outcomes
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.schemas import (
    CommoditiesDataset,
    CommodityAsset,
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


class _HistoryTarget(NamedTuple):
    """One deterministic history request and the consumers that require it."""

    domain: str
    symbol: str
    period: str
    consumers: tuple[str, ...]

    @property
    def request_key(self) -> str:
        return f"hist_{self.symbol}_{self.period}"


class _HistoryFetch(NamedTuple):
    """Worker result for one history target; shared state is merged by the caller."""

    target: _HistoryTarget
    rows: list[dict[str, Any]]
    meta: dict[str, Any]
    status: str
    error: str | None


# Breadth/trend and governed cross-asset diagnostic history. These ETF proxies are fetched
# through the same quotes registry once per generation; they are not added to the display
# universe. XLY/XLP and HYG/IEF remain diagnostic-only until the calibration policy permits
# them to affect production weights (#143).
INDEX_HISTORIES = {
    "SPY": "1y",
    "IWM": "1y",
    "SOXX": "1y",
    "XLY": "1y",
    "XLP": "1y",
    "HYG": "1y",
    "IEF": "1y",
}



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
        self._history_plan: tuple[_HistoryTarget, ...] = ()
        self._history_plan_keys: set[tuple[str, str, str]] = set()
        self._history_plan_ready = False
        self._history_fetched_keys: set[tuple[str, str, str]] = set()
        self._history_failures: dict[tuple[str, str, str], str] = {}
        self._history_meta: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._history_telemetry: list[dict[str, Any]] = []
        self._history_missing: list[dict[str, Any]] = []
        self._history_degraded: list[dict[str, Any]] = []
        self._dataset_degraded: set[str] = set()
        self._risk_history_degraded = False
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

    def _provider_for_any(self, domains: tuple[str, ...]) -> dict[str, Any]:
        """Resolve the first available internal route in deterministic order."""
        for domain in domains:
            if domain in self._provider_outcomes or self.registry.resolved_provider(domain) is not None:
                return self._provider_for(domain)
        return {"provider": "unavailable", "used_fallback": False, "from_cache": False}

    # ---- Quotes (US + A-shares) ----

    def _theme_history_symbols(self) -> set[str]:
        """Return the non-CN series symbols required by the configured themes."""
        symbols: set[str] = set()
        for theme in [*self.themes.sectors.values(), *self.themes.themes.values()]:
            if theme.proxy is not None and theme.proxy.kind == "etf" and theme.proxy.symbol:
                symbols.add(theme.proxy.symbol)
            else:
                symbols |= {c.symbol for c in theme.constituents if not c.symbol.endswith((".SH", ".SZ"))}
        return symbols

    def _build_history_plan(self) -> tuple[_HistoryTarget, ...]:
        """Build the single source of truth for market history collection.

        A target is deduplicated before any provider call. Consumer labels are metadata only;
        they make the request budget auditable without changing current scoring behavior.
        """
        consumers: dict[tuple[str, str, str], set[str]] = {}

        def add(domain: str, symbol: str, period: str, consumer: str) -> None:
            key = (domain, symbol, period)
            consumers.setdefault(key, set()).add(consumer)

        for asset in self.universe.us_equities:
            add("quotes", asset.symbol, "1y", "equity_card")
        for asset in self.universe.a_share_memory:
            add("a_share", asset.symbol, "1y", "equity_card")
        for symbol, period in INDEX_HISTORIES.items():
            add("quotes", symbol, period, "risk_breadth_trend")

        for symbol in self._theme_history_symbols():
            add("quotes", symbol, "1y", "themes")

        return tuple(
            _HistoryTarget(domain, symbol, period, tuple(sorted(consumers[(domain, symbol, period)])))
            for domain, symbol, period in sorted(consumers)
        )

    @staticmethod
    def _history_status(meta: dict[str, Any], rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "empty"
        if bool(meta.get("degraded") or meta.get("used_fallback") or meta.get("from_cache")):
            return "degraded"
        return "fresh"

    def _fetch_history_target(self, target: _HistoryTarget) -> _HistoryFetch:
        """Fetch one planned target without mutating collector state."""
        try:
            out = self.registry.call(
                target.domain,
                "get_history",
                target.request_key,
                args=(target.symbol, target.period),
            )
            rows = list(out["result"].rows or [])
            meta = dict(out.get("meta") or {})
            return _HistoryFetch(target, rows, meta, self._history_status(meta, rows), None)
        except ProviderError as exc:
            return _HistoryFetch(target, [], {}, "missing", str(exc))

    def _merge_history_fetches(self, fetched: list[_HistoryFetch]) -> None:
        """Merge ordered worker results and publish bounded request diagnostics."""
        for item in fetched:
            target = item.target
            key = (target.domain, target.symbol, target.period)
            self._history_fetched_keys.add(key)
            self._history_meta[key] = item.meta
            self.histories[target.symbol] = item.rows
            if item.meta:
                self._record_outcome(target.domain, item.meta)
            if item.error:
                self._history_failures[key] = item.error
                self.degraded.append(f"{target.symbol}: history unavailable")
                self.registry.degraded_domains.add(target.domain)
                self.provider_status.setdefault(target.domain, {})["error"] = item.error
            elif item.status == "empty":
                self.degraded.append(f"{target.symbol}: history empty")
                self.registry.degraded_domains.add(target.domain)
            elif item.status == "degraded":
                self.degraded.append(f"{target.symbol}: history served degraded")

            if item.status != "fresh":
                if "equity_card" in target.consumers:
                    self._dataset_degraded.add("equities")
                if "themes" in target.consumers:
                    self._dataset_degraded.add("sectors")
                if "risk_breadth_trend" in target.consumers:
                    self._risk_history_degraded = True

            telemetry = {
                "request_key": target.request_key,
                "domain": target.domain,
                "symbol": target.symbol,
                "period": target.period,
                "consumers": list(target.consumers),
                "requested": 1,
                "row_count": len(item.rows),
                "provider": str(item.meta.get("provider", "unavailable")),
                "used_fallback": bool(item.meta.get("used_fallback", False)),
                "from_cache": bool(item.meta.get("from_cache", False)),
                "status": item.status,
            }
            self._history_telemetry.append(telemetry)
            summary = {
                "request_key": target.request_key,
                "domain": target.domain,
                "symbol": target.symbol,
                "consumers": list(target.consumers),
                "status": item.status,
            }
            if item.status in ("missing", "empty"):
                self._history_missing.append(summary)
            elif item.status == "degraded":
                self._history_degraded.append(summary)

    def _collect_history_plan(self) -> None:
        """Collect all market histories once, in a bounded and deterministic request plan."""
        self._history_plan = self._build_history_plan()
        self._history_plan_keys = {(t.domain, t.symbol, t.period) for t in self._history_plan}
        self._history_plan_ready = True
        if not self._history_plan:
            return
        targets = tuple(
            target
            for target in self._history_plan
            if (target.domain, target.symbol, target.period) not in self._history_fetched_keys
        )
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            fetched = list(pool.map(self._fetch_history_target, targets))
        self._merge_history_fetches(fetched)

    def _history_for_asset(self, asset: Any) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
        """Read a planned history, or retain the legacy direct-helper fallback."""
        domain = "quotes" if asset.market == "US" else "a_share"
        key = (domain, asset.symbol, "1y")
        if self._history_plan_ready and key in self._history_plan_keys:
            return (
                self.histories.get(asset.symbol, []),
                self._history_failures.get(key),
                self._history_meta.get(key, {}),
            )
        try:
            out = self.registry.call(domain, "get_history", f"hist_{asset.symbol}_1y", args=(asset.symbol, "1y"))
            rows = list(out["result"].rows or [])
            self._record_outcome(domain, out["meta"])
            return rows, None, dict(out.get("meta") or {})
        except ProviderError as exc:
            return [], str(exc), {}

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

        # #85 (fix): quote and history are DECOUPLED. They used to be one atomic try — a
        # cached quote was thrown away the moment the history call failed (the A-share
        # cache held a valid quote while `hist_*_1y` was absent, so every symbol was
        # dropped even though the price was recovered). A symbol with a quote but no
        # history publishes with honest None technicals; only a quote failure drops it.
        try:
            quote_out = self.registry.call(domain, "get_quote", f"quote_{asset.symbol}", args=(asset.symbol,))
            outcomes[domain] = quote_out["meta"]
        except ProviderError as exc:
            degraded.append(f"{asset.symbol}: {exc}")
            status_error = str(exc)
            return _EquityFetch(None, domain, degraded, outcomes, status_error, [])

        quote = quote_out["result"]
        rows, history_error, history_meta = self._history_for_asset(asset)
        if history_meta:
            outcomes[domain] = {
                **quote_out["meta"],
                "used_fallback": bool(quote_out["meta"].get("used_fallback") or history_meta.get("used_fallback")),
                "from_cache": bool(quote_out["meta"].get("from_cache") or history_meta.get("from_cache")),
                "degraded": bool(
                    quote_out["meta"].get("degraded")
                    or history_meta.get("degraded")
                    or history_meta.get("used_fallback")
                    or history_meta.get("from_cache")
                ),
            }
        if history_error:
            if not self._history_plan_ready:
                degraded.append(f"{asset.symbol}: history unavailable: {history_error}")
            status_error = history_error
            outcomes[domain] = {**quote_out["meta"], "degraded": True}
            # ADR 0004: degradation costs quality. The registry marks the domain degraded
            # on fallback/cache reads — a history-only failure does not reach it (the call
            # raised), so the collector records it here or the None-technical assets ship
            # at full data_quality.
            self.registry.degraded_domains.add(domain)
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
            if degraded or status_error or any(bool(meta.get("degraded")) for meta in outcomes.values()):
                self._dataset_degraded.add("equities")
                if not degraded and not status_error:
                    self.degraded.append(f"{domain}: provider served degraded data")
            if status_error:
                self.provider_status.setdefault(domain, {})["error"] = status_error
        return EquitiesDataset(assets=assets)

    # ---- Index history (breadth/trend) ----

    def _collect_index_histories(self) -> None:
        # Kept as a direct helper for callers/tests. A normal collection uses the complete
        # plan from ``_collect_history_plan`` and therefore never enters this subset.
        if self._history_plan_ready:
            return
        targets = tuple(
            _HistoryTarget("quotes", symbol, period, ("risk_breadth_trend",))
            for symbol, period in INDEX_HISTORIES.items()
            if ("quotes", symbol, period) not in self._history_fetched_keys
        )
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            fetched = list(pool.map(self._fetch_history_target, targets))
        self._merge_history_fetches(fetched)

    # ---- Crypto ----

    def _collect_crypto(self) -> CryptoDataset:
        try:
            out = self.registry.call("crypto", "get_crypto_market", "crypto_market")
            data = out["result"]
            self.provider_status["crypto"] = out["meta"]
            self._record_outcome("crypto", out["meta"])
            if out["meta"].get("degraded"):
                self._dataset_degraded.add("crypto")
                self.degraded.append("crypto: provider served degraded data")
        except ProviderError as exc:
            self.degraded.append(f"crypto: {exc}")
            self._dataset_degraded.add("crypto")
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

    # ---- Commodities (metals + oil, universe.yaml) ----

    def _collect_commodities(self) -> CommoditiesDataset:
        """Collect the commodities universe (gold/silver/copper/oil) via the quotes domain.

        Universe symbols (GC=F / SI=F / HG=F / CL=F) pass straight through Yahoo's identity
        symbol mapper, and FMP serves the same keys as the fallback. A quote failure drops
        the asset (degraded) — the honest shape, matching ``_fetch_equity``.
        """
        targets = [*self.universe.metals, *self.universe.oil]
        assets: list[CommodityAsset] = []
        for asset in targets:
            try:
                out = self.registry.call("quotes", "get_quote", f"quote_{asset.symbol}", args=(asset.symbol,))
            except ProviderError as exc:
                self.degraded.append(f"{asset.symbol}: {exc}")
                self._dataset_degraded.add("commodities")
                self.provider_status.setdefault("quotes", {})["error"] = str(exc)
                continue
            self._record_outcome("quotes", out["meta"])
            if out["meta"].get("degraded"):
                self._dataset_degraded.add("commodities")
                self.degraded.append(f"{asset.symbol}: provider served degraded data")
            quote = out["result"]
            assets.append(
                CommodityAsset(
                    symbol=asset.symbol,
                    name=asset.name,
                    name_zh=asset.name_zh,
                    price=quote.price,
                    currency="USD",
                    change_1d=quote.change_1d,
                    change_1w=quote.change_1w,
                    change_1m=quote.change_1m,
                    source=quote.source,
                    updated_at=quote.updated_at or now_utc(),
                )
            )
        return CommoditiesDataset(assets=assets)

    # ---- Sectors/themes ----

    def _collect_sectors(self, equities: EquitiesDataset) -> SectorsDataset:
        def _row(key: str, theme: Any) -> SectorItem:
            """Build one row from a themes.yaml definition (C-1/#102).

            Sectors AND themes are both series-based (#93/#86 §4.5): card numbers and
            ``percentile_1y`` come from the same series, so they provably describe the same
            object, and no row ships the banned ``percentile None / obs 0`` shape.
            """
            rows = self._theme_series(theme)
            item = SectorItem(
                key=key,
                constituents=[c.symbol for c in theme.constituents],
                updated_at=now_utc(),
            )
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
            return item

        # Fetch every series symbol ONCE, in a bounded thread pool, before any row is built
        # (#93 DoD 7: the #91 run budget is kept by parallelism + the registry's per-host
        # limiter instead of ~130 sequential fetches).
        self._prefetch_theme_series()
        sectors = [_row(key, theme) for key, theme in self.themes.sectors.items()]
        themes = self._collect_themes(_row)
        if any(
            "themes" in item["consumers"] and item["status"] != "fresh"
            for item in self._history_telemetry
        ):
            self._dataset_degraded.add("sectors")

        # Memory cycle proxy (review P0-1): kept as its own object because the frontend
        # renders it as a single prose card; its numbers now come from the memory THEME
        # series (the proxy's change_1w/1m are the theme basket's, #93 supersedes the block).
        memory_series = next((t for t in themes if t.key == "memory"), None)
        memory = MemoryProxy(
            label="Memory cycle proxy (sector: memory basket)",
            label_zh="存储周期代理（板块：存储篮子）",
            change_1w=memory_series.change_1w if memory_series else None,
            change_1m=memory_series.change_1m if memory_series else None,
            note="DRAM/NAND spot prices are paywalled; the memory sector basket series proxies the cycle (#93 supersedes the MU-only proxy)",
            updated_at=now_utc(),
        )
        return SectorsDataset(sectors=sectors, themes=themes, memory=memory)

    def _prefetch_theme_series(self) -> None:
        """Fetch every symbol behind the sector/theme series once, in a bounded thread pool.

        ETF proxies and basket constituents are deduplicated (a symbol in several themes is
        fetched once), the already-fetched card histories are reused, and A-share members are
        skipped (akshare's historical kline tier is blocked from this host per #85). Results
        are merged into ``self.histories`` in the caller's thread — workers never write
        shared state.
        """
        needed = self._theme_history_symbols()
        targets = sorted(
            s
            for s in needed
            if s not in self.histories
            and (not self._history_plan_ready or ("quotes", s, "1y") not in self._history_plan_keys)
        )
        if not targets:
            return
        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            fetched = list(pool.map(self._fetch_series_rows, targets))
        for symbol, rows in fetched:
            if rows and len(rows) >= 2:
                self.histories[symbol] = rows

    def _fetch_series_rows(self, symbol: str) -> tuple[str, list[dict[str, Any]]]:
        """One thread worker: fetch a symbol's 1y history (no shared-state writes)."""
        try:
            out = self.registry.call("quotes", "get_history", f"hist_{symbol}_1y", args=(symbol, "1y"))
            return symbol, out["result"].rows
        except ProviderError:
            return symbol, []

    def _collect_themes(self, row_builder: Any) -> list[SectorItem]:
        """Build the 20 theme rows, then run the D-1 identical-series guard (#93/#86 §4)."""
        themes = [row_builder(key, theme) for key, theme in self.themes.themes.items()]

        # D-1 regression: no two themes may publish identical series. The old `ai` row was
        # byte-identical to `semis`; a repeat is a config/collection bug and fails loudly
        # (like the taxonomy guards) — a true identical-series is not a coincidence.
        fingerprints: dict[tuple, str] = {}
        for item in themes:
            series = self._theme_series(self.themes.themes[item.key])
            fingerprint = tuple(round(r["close"], 4) for r in series if r.get("close") is not None)[:120]
            if not fingerprint:
                continue
            if fingerprint in fingerprints:
                raise RuntimeError(
                    f"themes {fingerprints[fingerprint]!r} and {item.key!r} publish identical "
                    f"series (D-1 guard, #93)"
                )
            fingerprints[fingerprint] = item.key
        return themes

    def _theme_series(self, theme: Any) -> list[dict[str, Any]]:
        """The 1y close series behind one sector/theme (#93): the ETF's own series, or the
        equal-weight basket chained from constituent histories already in ``self.histories``."""
        from pipeline.indicators.themes import chain_equal_weight_daily

        if theme.proxy is not None and theme.proxy.kind == "etf":
            return self.histories.get(theme.proxy.symbol, [])
        series_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for constituent in theme.constituents:
            if constituent.symbol.endswith((".SH", ".SZ")):
                continue  # #85: akshare's historical kline tier is blocked — no fake series
            rows = self.histories.get(constituent.symbol, [])
            if rows and len(rows) >= 2:
                series_by_symbol[constituent.symbol] = rows
        if not series_by_symbol:
            return []
        return chain_equal_weight_daily(series_by_symbol)

    # ---- Summary ----

    def _quality(self) -> float:
        """Quality is scoped to the market collector's own outcomes."""
        return quality_for_outcomes(
            [name in self._dataset_degraded for name in ("equities", "crypto", "commodities", "sectors")],
            settings=self.settings,
        )

    def _reset_collection_state(self) -> None:
        """Clear generation-local market state when a collector instance is reused."""
        self.degraded.clear()
        self.provider_status.clear()
        self.histories.clear()
        self._provider_outcomes.clear()
        self._history_plan = ()
        self._history_plan_keys.clear()
        self._history_plan_ready = False
        self._history_fetched_keys.clear()
        self._history_failures.clear()
        self._history_meta.clear()
        self._history_telemetry.clear()
        self._history_missing.clear()
        self._history_degraded.clear()
        self._dataset_degraded.clear()
        self._risk_history_degraded = False

    def _sectors_degraded_detail(self) -> str:
        """A human-readable detail behind the sectors degraded flag (#174).

        Names the theme history requests that were not fresh — the same telemetry that
        marks ``sectors`` degraded in ``_merge_history_fetches`` — so the Status page
        reason says *which* series failed instead of a bare ``provider_http_error``.
        Returns an empty string when no theme series failed.
        """
        failed = sorted(
            item["request_key"]
            for item in self._history_telemetry
            if "themes" in item["consumers"] and item["status"] != "fresh"
        )
        return "theme series unavailable: " + ", ".join(failed) if failed else ""

    def _collection_telemetry(self) -> dict[str, Any]:
        """Return bounded, provider-safe diagnostics for the market history plan."""
        request_keys = {item["request_key"] for item in self._history_telemetry}
        return {
            "history_plan_count": len(self._history_plan),
            "history_request_count": len(self._history_telemetry),
            "request_keys": sorted(request_keys),
            "unique_request_keys": len(request_keys),
            "duplicate_request_keys": len(self._history_telemetry) - len(request_keys),
            "history_requests": self._history_telemetry,
            "missing_inputs": self._history_missing,
            "degraded_inputs": self._history_degraded,
        }

    def collect(self) -> dict[str, Any]:
        self._reset_collection_state()
        self._collect_history_plan()
        equities = self._collect_equities()
        crypto = self._collect_crypto()
        commodities = self._collect_commodities()
        sectors = self._collect_sectors(equities)
        quality_by_dataset = {
            name: quality_for_outcomes([name in self._dataset_degraded], settings=self.settings)
            for name in ("equities", "crypto", "commodities", "sectors")
        }
        quality = round(sum(quality_by_dataset.values()) / len(quality_by_dataset), 3)
        risk_input_quality = quality_for_outcomes([self._risk_history_degraded], settings=self.settings)
        risk_data_quality = round(
            (
                sum(quality_by_dataset[name] for name in ("equities", "crypto", "commodities"))
                + risk_input_quality
            )
            / 4,
            3,
        )
        source_by_dataset = {
            # Quote adapters currently expose local fetch time only, while the equity card
            # combines that quote with historical observations. One unknown contributor
            # makes the dataset-level provenance unknown.
            "equities": None,
            # CoinGecko currently does not expose a trustworthy dataset-level timestamp in its
            # normalized provider result; do not substitute the local fetch time.
            "crypto": None,
            # Quote adapters expose local fetch time only; no upstream observation timestamp is
            # published as provenance until a provider supplies one explicitly.
            "commodities": None,
            "sectors": (
                None
                if "sectors" in self._dataset_degraded
                else oldest_source_timestamp(
                    latest_row_timestamp(self.histories.get(target.symbol, []))
                    for target in self._history_plan
                    if "themes" in target.consumers
                )
            ),
        }

        # #64/#65: collectors return payloads + provider outcome; the caller (run.py) assembles
        # the envelope through the single assembly path and finalizes freshness + provenance.
        return {
            "equities": equities,
            "crypto": crypto,
            "commodities": commodities,
            "sectors": sectors,
            "histories": self.histories,
            "degraded": self.degraded,
            # ``quotes`` and ``a_share`` are internal routes within the canonical market
            # domain. Keep their diagnostics available on ``self.provider_status`` for direct
            # collector callers, but publish only the canonical status domain (#136).
            "provider_status": {
                "market": {
                    "collection_telemetry": self._collection_telemetry(),
                }
            },
            "data_quality": round(quality, 3),
            "data_quality_by_dataset": quality_by_dataset,
            "degraded_by_dataset": {
                name: name in self._dataset_degraded for name in quality_by_dataset
            },
            # #174: per-dataset human-readable detail behind the degraded flag. Sectors name
            # the theme series whose 1y history was unavailable/empty/degraded — the failed
            # request keys were already in collection_telemetry, this surfaces them on the
            # Status page reason instead of burying them in sources.json.
            "degraded_detail_by_dataset": {
                "sectors": self._sectors_degraded_detail(),
            },
            "source_updated_at_by_dataset": source_by_dataset,
            "risk_data_quality": risk_data_quality,
            "risk_history_degraded": self._risk_history_degraded,
            "providers": {
                "equities": self._provider_for_any(("quotes", "a_share")),
                "crypto": self._provider_for("crypto"),
                "commodities": self._provider_for("quotes"),
                "sectors": self._provider_for("quotes"),
            },
        }
