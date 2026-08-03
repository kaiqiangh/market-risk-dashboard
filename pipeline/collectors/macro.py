"""Macro collector (architecture §3.7 MacroCollector).

FRED series + FedWatch probabilities (Yahoo ZQ futures + EFFR anchor + local snapshot accumulation).
Any Provider failure → degradation chain → degraded, does not interrupt the pipeline.
"""

from __future__ import annotations

from typing import Any

from pipeline.fedwatch import (
    FedWatchInput,
    compute_fedwatch,
    enrich_with_history,
    fetch_contract_price,
    insufficient_data_snapshot,
    load_history,
    meeting_date_for_contract,
    next_contract_codes,
    save_history,
)
from pipeline.providers.base import ProviderError, ProviderRegistry
from pipeline.providers.fred import SERIES_CATALOG
from pipeline.schemas import FedWatchSnapshot, MacroDataset, MacroEnvelope, MacroIndicator
from pipeline.settings import Settings
from pipeline.utils import now_utc

# FRED series → group
SERIES_GROUPS: dict[str, list[str]] = {
    "rates": ["DGS10", "DGS2", "DFII10", "T10YIE", "DFF"],
    "credit": ["BAMLH0A0HYM2", "BAMLC0A0CM"],
    "inflation": ["CPIAUCSL", "PCEPI"],
    "labor": ["UNRATE", "PAYEMS"],
    "liquidity": ["WALCL", "RRPONTSYD", "WTREGEN", "WRESBAL"],
    "fx": ["DTWEXBGS"],
}

DEFAULT_SERIES = ["DGS10", "DGS2", "DFII10", "T10YIE", "DFF", "BAMLH0A0HYM2", "BAMLC0A0CM", "VIXCLS"]


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

    # ---- FRED ----

    def _fred_series(self, series_id: str) -> list[dict[str, Any]]:
        try:
            out = self.registry.call("macro", "get_series", f"fred_{series_id}", args=(series_id,))
            self.provider_status.setdefault("macro", out["meta"])
            rows = out["result"]
            # Normalize to lowercase keys: the risk model 5Y percentile looks up by the lowercase
            # series name of the indicator key
            self.series_history[series_id.lower()] = rows
            return rows
        except ProviderError as exc:
            self.degraded.append(str(exc))
            self._fred_failures += 1
            self.provider_status["macro"] = {"degraded": True, "error": str(exc)}
            return []

    def _collect_macro(self) -> MacroDataset:
        groups: dict[str, list[MacroIndicator]] = {g: [] for g in SERIES_GROUPS}
        for series_id in DEFAULT_SERIES:
            rows = self._fred_series(series_id)
            if not rows:
                continue
            catalog = SERIES_CATALOG.get(series_id, {"label": series_id, "unit": "level"})
            indicator = MacroIndicator(
                key=series_id.lower(),
                label=catalog["label"],
                value=rows[-1]["value"],
                previous=rows[-2]["value"] if len(rows) > 1 else None,
                change_1m=_change(rows, 21),
                unit=_unit(catalog.get("unit", "level")),
                source="FRED",
                updated_at=_utc_from_date(rows[-1]["date"]),
                status="fresh" if len(rows) >= 2 else "stale",
            )
            group = _group_of(series_id)
            groups[group].append(indicator)
        return MacroDataset(
            rates=groups["rates"],
            credit=groups["credit"],
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
            self.degraded.append("FedWatch: no EFFR anchor")
            return self._accumulate(insufficient_data_snapshot(None))

        prices: dict[str, float | None] = {}
        for code in next_contract_codes():
            try:
                prices[code] = fetch_contract_price(code)
            except ProviderError as exc:
                self.degraded.append(f"FedWatch {code}: {exc}")
                prices[code] = None

        codes = next_contract_codes()
        if not any(v is not None for v in prices.values()):
            self._fedwatch_failed = True
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
        """Data quality degrades ×0.8 per failed source: FRED partial failure counts as 1, FedWatch failure counts as 1."""
        failed = (1 if self._fred_failures > 0 else 0) + (1 if self._fedwatch_failed else 0)
        return round(max(0.1, 0.8 ** failed), 3)

    def collect(self) -> tuple[MacroEnvelope, dict[str, Any]]:
        dataset = self._collect_macro()
        quality = self._quality()
        envelope = MacroEnvelope(
            generated_at=now_utc(),
            schema_version="1.0.0",
            source=["fred", "yahoo"],
            source_updated_at=now_utc(),
            freshness_status="degraded" if self.degraded else "fresh",
            data_quality=round(quality, 3),
            payload=dataset,
        )
        return envelope, {
            "degraded": self.degraded,
            "provider_status": self.provider_status,
            "series_history": self.series_history,
        }


def _change(rows: list[dict], lookback: int) -> float | None:
    if len(rows) < 2:
        return None
    idx = min(lookback, len(rows) - 1)
    return round(rows[-1]["value"] - rows[-idx]["value"], 6)


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
    return "rates"


def _utc_from_date(date_str: str) -> str | None:
    if not date_str:
        return None
    return f"{date_str}T00:00:00Z"
