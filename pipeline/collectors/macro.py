"""Macro collector (architecture §3.7 MacroCollector).

FRED series + FedWatch probabilities (Yahoo ZQ futures + EFFR anchor + local snapshot accumulation).
Any Provider failure → degradation chain → degraded, does not interrupt the pipeline.

#96 (uses #84): the 27-series roster across 7 groups (incl. a new `volatility` group for
VIXCLS), every request bounded to the 5y window and memoised, units transformed
server-side (pc1/chg), frequency-aware change/status, per-series history archived for the
risk model's percentile windows. Refresh cadence: FRED runs on `--full`/`--macro-only`
(2 runs/day against the automation schedule); 27 bounded requests ≈ 2 MB/run — payload
size, not rate limits, was the constraint (#84 §4).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from pipeline.fedwatch import (
    FedWatchInput,
    compute_fedwatch,
    enrich_with_history,
    insufficient_data_snapshot,
    load_history,
    meeting_date_for_contract,
    next_contract_codes,
    save_history,
)
from pipeline.metadata import oldest_source_timestamp, quality_for_outcomes
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.providers.fred import DEFAULT_SERIES_META, SERIES_CATALOG
from pipeline.schemas import FedWatchSnapshot, MacroDataset, MacroIndicator
from pipeline.settings import Settings

# FRED series → group (#96, uses #84 §1 roster). VIXCLS moved to its own `volatility`
# group (it is an equity implied-volatility index, not a rate); T10YIE moved to
# `inflation` (an expectation measure, not a rate).
SERIES_GROUPS: dict[str, list[str]] = {
    "rates": ["DGS10", "DGS2", "DFII10", "DFF"],
    "credit": ["BAMLH0A0HYM2", "BAMLC0A0CM"],
    "volatility": ["VIXCLS"],
    "inflation": ["CPIAUCSL", "CPILFESL", "PCEPILFE", "T5YIFR", "T10YIE"],
    "labor": ["PAYEMS", "UNRATE", "ICSA", "CCSA", "CIVPART"],
    "liquidity": ["WALCL", "WRESBAL", "WTREGEN", "RRPONTSYD", "SOFR"],
    "fx": ["DTWEXBGS", "DTWEXAFEGS", "DEXUSEU", "DEXJPUS", "DEXCHUS"],
}

# #84 §0: the four empty categories were a wiring gap between SERIES_GROUPS (15 ids) and
# DEFAULT_SERIES (8 ids) that drifted apart. One list now: the fetch loop iterates the
# grouping table, so a new series added to a group is fetched by construction.
DEFAULT_SERIES: list[str] = [s for group in SERIES_GROUPS.values() for s in group]

#: Frequency spec — one table, three consumers (#84 §6a/§6b): change_1m lookback in ROWS
#: (21 rows is ~1 month only for daily series; a monthly series would show 21 months
#: labelled "1m"), staleness threshold in DAYS since the last observation (a row-count
#: "fresh" is not a freshness measure), and the history manifest's next-release estimate.
#: Three parallel maps would drift; one table cannot.
FREQ_SPEC: dict[str, dict[str, int]] = {
    "daily": {"lookback": 21, "stale_days": 7, "next_days": 2},
    "weekly": {"lookback": 4, "stale_days": 21, "next_days": 8},
    "monthly": {"lookback": 1, "stale_days": 75, "next_days": 32},
}

#: FRED fetch window (#84 §4): bound every request to 5y — the full-history download was
#: 7.26 MB/run for 8 series (DGS10 alone 1563 KB back to 1962); the 27-series roster with
#: observation_start ≈ 2 MB.
MACRO_LOOKBACK_DAYS = 5 * 365


class MacroCollector:
    def __init__(self, registry: ProviderRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings or Settings()
        self.degraded: list[str] = []
        self.provider_status: dict[str, Any] = {}
        # Full series history (Fix P0-2: for the risk model 5Y percentile window)
        self.series_history: dict[str, list[dict[str, Any]]] = {}
        self._fred_failures = 0
        self._fedwatch_failed = False
        # #84 §4: memoise _fred_series — DFF used to be fetched twice per run (DEFAULT_SERIES
        # + the FedWatch anchor), a wasted 2.4 MB.
        self._fred_cache: dict[str, list[dict[str, Any]]] = {}
        #: Domain → provider outcome of the most recent successful call (#65).
        self._provider_outcomes: dict[str, dict[str, Any]] = {}
        self._degraded_sources: set[str] = set()

    # ---- FRED ----

    def _fred_series(self, series_id: str) -> list[dict[str, Any]]:
        if series_id in self._fred_cache:
            return self._fred_cache[series_id]
        catalog = SERIES_CATALOG.get(series_id, {})
        # #84 §4: observation_start bounds every request to the 5y window (the risk model's
        # percentile window) — the full-history download was ~7 MB/run for 8 series.
        start = (datetime.now(timezone.utc).date() - timedelta(days=MACRO_LOOKBACK_DAYS)).isoformat()
        units = catalog.get("units", "lin")
        try:
            out = self.registry.call(
                "macro", "get_series", f"fred_{series_id}",
                args=(series_id,), kwargs={"start": start, "units": units},
            )
            if "macro" not in self.provider_status or out["meta"].get("degraded"):
                self.provider_status["macro"] = out["meta"]
            self._provider_outcomes["macro"] = out["meta"]
            if out["meta"].get("degraded"):
                self._degraded_sources.add("fred")
                self.degraded.append(f"FRED {series_id}: provider served degraded data")
            rows = out["result"]
            # Normalize to lowercase keys: the risk model 5Y percentile looks up by the lowercase
            # series name of the indicator key
            self.series_history[series_id.lower()] = rows
            self._fred_cache[series_id] = rows
            return rows
        except ProviderError as exc:
            self.degraded.append(str(exc))
            self._fred_failures += 1
            self._degraded_sources.add("fred")
            self.provider_status["macro"] = {"degraded": True, "error": str(exc)}
            return []

    def _collect_macro(self) -> MacroDataset:
        groups: dict[str, list[MacroIndicator]] = {g: [] for g in SERIES_GROUPS}
        for series_id in DEFAULT_SERIES:
            rows = self._fred_series(series_id)
            if not rows:
                continue
            catalog = SERIES_CATALOG.get(series_id, {**DEFAULT_SERIES_META, "label": series_id})
            frequency = catalog.get("frequency", "daily")
            indicator = MacroIndicator(
                key=series_id.lower(),
                label=catalog["label"],
                value=rows[-1]["value"],
                previous=rows[-2]["value"] if len(rows) > 1 else None,
                # #84 §6a: the change lookback derives from the series' frequency — 21
                # rows is one month only for daily series.
                change_1m=_change(rows, FREQ_SPEC.get(frequency, FREQ_SPEC["daily"])["lookback"]),
                unit=_unit(catalog.get("unit", "level")),
                source="FRED",
                updated_at=_utc_from_date(rows[-1]["date"]),
                # #84 §6b: per-indicator status is judged against the series' own cadence
                # (a monthly series unchanged for 30 days is fresh; a daily series 10 days
                # behind is stale), not a row count.
                status=_series_status(rows[-1]["date"], frequency),
            )
            group = _group_of(series_id)
            groups[group].append(indicator)
        return MacroDataset(
            rates=groups["rates"],
            credit=groups["credit"],
            volatility=groups["volatility"],
            inflation=groups["inflation"],
            labor=groups["labor"],
            liquidity=groups["liquidity"],
            fx=groups["fx"],
            fedwatch=self._collect_fedwatch(),
        )

    # ---- FedWatch ----

    def _collect_fedwatch(self) -> FedWatchSnapshot | None:
        # EFFR anchor (DFF preferred, fallback EFFR)
        effr: float | None = None
        for series_id in ("DFF", "EFFR"):
            rows = self._fred_series(series_id)
            if rows:
                effr = rows[-1]["value"]
                break
        if effr is None:
            self._fedwatch_failed = True
            self._degraded_sources.add("fedwatch")
            self.degraded.append("FedWatch: no EFFR anchor")
            return self._accumulate(insufficient_data_snapshot(None))

        codes = next_contract_codes()
        try:
            out = self.registry.call("fedwatch", "get_contract_prices", "fedwatch_contracts", args=(codes,))
            prices: dict[str, float | None] = out["result"]
            self.provider_status["fedwatch"] = out["meta"]
            if out["meta"].get("degraded"):
                self._degraded_sources.add("fedwatch")
                self.degraded.append("FedWatch: provider served degraded data")
        except ProviderError as exc:
            prices = {}
            self.provider_status["fedwatch"] = {"degraded": True, "error": str(exc)}
            self.degraded.append(f"FedWatch: {exc}")
            self._degraded_sources.add("fedwatch")

        if not any(v is not None for v in prices.values()):
            self._fedwatch_failed = True
            self._degraded_sources.add("fedwatch")
            self.degraded.append("FedWatch: ZQ futures unavailable")
            return self._accumulate(insufficient_data_snapshot(effr))

        snapshot = compute_fedwatch(
            FedWatchInput(
                current_contract_price=prices.get(codes[0]) if len(codes) > 0 else None,
                next_contract_price=prices.get(codes[1]) if len(codes) > 1 else None,
                effr=effr,
                meeting_date=meeting_date_for_contract(codes[0]) if len(codes) > 0 else None,
            )
        )
        if snapshot is None:
            return self._accumulate(insufficient_data_snapshot(effr))
        return self._accumulate(snapshot)

    def _accumulate(self, snapshot: FedWatchSnapshot) -> FedWatchSnapshot:
        """Local daily snapshot accumulation (architecture §1.6/review P0-1): build the accumulation file regardless of success."""
        history_path = self.settings.data_dir / "feeds" / "fedwatch-history.json"
        history = load_history(history_path)
        enriched = enrich_with_history(snapshot, history, history_path)
        save_history(history_path, history)
        return enriched
    # ---- Summary ----

    def _quality(self) -> float:
        """Data quality degrades by the configured factor per failed source.

        FRED partial failure counts as one source, FedWatch failure counts as one.
        """
        return quality_for_outcomes(
            [source in self._degraded_sources for source in ("fred", "fedwatch")],
            settings=self.settings,
        )

    def collect(self) -> tuple[MacroDataset, dict[str, Any]]:
        dataset = self._collect_macro()
        quality = self._quality()
        indicator_times = [
            indicator.updated_at
            for group in SERIES_GROUPS
            for indicator in getattr(dataset, group)
        ]
        source_updated_at = (
            oldest_source_timestamp(indicator_times)
            if (
                len(indicator_times) == len(DEFAULT_SERIES)
                and not self._degraded_sources
                # FedWatch combines FRED with futures whose adapter result has no
                # trustworthy upstream observation timestamp.
                and dataset.fedwatch is None
            )
            else None
        )
        # #64: return payload + provider outcome; the caller assembles the envelope and
        # finalizes freshness through the single assembly path.
        outcome = self._provider_outcomes.get("macro") or self.registry.resolved_provider("macro")
        if outcome is None:
            outcome = {"provider": "unavailable", "used_fallback": False, "from_cache": False}
        return dataset, {
            "degraded": self.degraded,
            "provider_status": self.provider_status,
            "series_history": self.series_history,
            "data_quality": round(quality, 3),
            "source_updated_at": source_updated_at,
            "provider": {
                "provider": str(outcome.get("provider", "unavailable")),
                "used_fallback": bool(outcome.get("used_fallback", False)),
                "from_cache": bool(outcome.get("from_cache", False)),
            },
        }


def _change(rows: list[dict], lookback: int) -> float | None:
    """Change over exactly `lookback` periods, consistent with `momentum` (#70).

    The base is `lookback` periods before the latest (`rows[-1 - lookback]`); the previous
    off-by-one used `rows[-lookback]`, which is one period closer and understated the span.
    """
    if len(rows) < 2:
        return None
    periods = min(lookback, len(rows) - 1)
    return round(rows[-1]["value"] - rows[-1 - periods]["value"], 6)


def _unit(unit: str) -> str:
    if unit == "pct":
        return "pct"
    if unit == "usd":
        return "usd"
    if unit == "index":
        return "index"
    return "level"


def _group_of(series_id: str) -> str:
    for group, series_list in SERIES_GROUPS.items():
        if series_id in series_list:
            return group
    # #84 §5: an unmapped series used to misfile itself under "rates" silently. With the
    # roster now derived from this table an unmapped id is a wiring mistake — fail loud.
    raise KeyError(f"macro: {series_id!r} is not mapped in SERIES_GROUPS")


def _series_status(last_date: str, frequency: str) -> str:
    """Per-indicator status against the series' OWN cadence (#84 §6b).

    A row-count "fresh" is not a freshness measure: a discontinued series with thousands
    of rows ending in 2019 reported `fresh`. A monthly series unchanged for 30 days IS
    fresh; a daily series 10 days behind is stale. Thresholds are a grace multiple of the
    frequency. (The full release-calendar model — next_expected_release per series in the
    history manifest — is future work; this is the minimal honest version.)
    """
    try:
        # §8.2: compare against UTC, not the host's local date.
        age_days = (datetime.now(timezone.utc).date() - date.fromisoformat(last_date)).days
    except ValueError:
        return "stale"
    threshold = FREQ_SPEC.get(frequency, FREQ_SPEC["daily"])["stale_days"]
    return "fresh" if age_days <= threshold else "stale"


def _utc_from_date(date_str: str) -> str | None:
    if not date_str:
        return None
    return f"{date_str}T00:00:00Z"
