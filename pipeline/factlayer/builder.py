"""Fact layer assembly (architecture §3.3 FactLayerBuilder: AI input contract).

Language-neutral deterministic facts; the evidence_index entries are for the AI to cite (validated by validate.py).
"""

from __future__ import annotations

from typing import Any

from pipeline.schemas import (
    CalendarEnvelope,
    CryptoEnvelope,
    EquitiesEnvelope,
    EvidenceRef,
    FactLayer,
    MacroEnvelope,
    NewsEnvelope,
    RiskEnvelope,
    RiskModelResult,
    SectorsEnvelope,
)
from pipeline.schemas.envelope import SCHEMA_VERSION
from pipeline.utils import now_utc


class FactLayerBuilder:
    def build(
        self,
        *,
        risk: RiskEnvelope,
        macro: MacroEnvelope,
        equities: EquitiesEnvelope,
        crypto: CryptoEnvelope,
        news: NewsEnvelope,
        calendar: CalendarEnvelope,
        sectors: SectorsEnvelope | None = None,
        generated_at: str | None = None,
    ) -> FactLayer:
        """Assemble the fact layer from the observed envelopes.

        Ruling E (#66): a rebuild is not an observation. ``generated_at`` defaults to ``now``
        for a fresh build (the pipeline just observed the data), but a rebuild passes the
        original ``fetched_at`` so the facts never re-stamp data as freshly fetched.
        """
        envs = {
            "macro": macro,
            "equities": equities,
            "crypto": crypto,
            "news": news,
            "calendar": calendar,
        }
        if sectors is not None:
            envs["sectors"] = sectors

        data_freshness = {key: env.freshness_status for key, env in envs.items()}
        data_freshness["risk"] = risk.freshness_status

        evidence_index = self._build_evidence(risk, macro, equities, crypto, news, calendar, sectors)

        return FactLayer(
            generated_at=generated_at or now_utc(),
            schema_version=SCHEMA_VERSION,
            data_freshness=data_freshness,
            risk=risk.payload,
            macro_summary=self._macro_summary(macro),
            market_summary=self._market_summary(equities, crypto, sectors),
            news_top=[n.model_dump() for n in news.payload.items[:15]],
            calendar_next7d=[e.model_dump() for e in calendar.payload.events[:20]],
            evidence_index=evidence_index,
        )

    # ---- Summaries ----

    def _macro_summary(self, macro: MacroEnvelope) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        # #96: volatility is a first-class group. The roster is imported — a literal copy
        # here would recreate the two-lists drift this ticket killed (review, #96).
        from pipeline.collectors.macro import SERIES_GROUPS

        for group in SERIES_GROUPS:
            for ind in getattr(macro.payload, group):
                summary[ind.key] = ind.value
                if ind.previous is not None:
                    summary[f"{ind.key}_prev"] = ind.previous
        if macro.payload.fedwatch is not None:
            fw = macro.payload.fedwatch
            summary["fedwatch_implied_rate"] = fw.implied_rate
            summary["fedwatch_action"] = fw.inferred_action
            summary["fedwatch_status"] = fw.status
        return summary

    def _market_summary(self, equities: EquitiesEnvelope, crypto: CryptoEnvelope,
                        sectors: SectorsEnvelope | None = None) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for asset in equities.payload.assets[:8]:
            summary[f"{asset.symbol.lower()}_price"] = asset.price
            summary[f"{asset.symbol.lower()}_change_1d"] = asset.change_1d
            summary[f"{asset.symbol.lower()}_change_1w"] = asset.change_1w
        for asset in crypto.payload.assets:
            summary[f"{asset.symbol.lower()}_price"] = asset.price
            summary[f"{asset.symbol.lower()}_change_1d"] = asset.change_1d
        summary["btc_dominance"] = crypto.payload.btc_dominance
        if sectors is not None:
            # #98: the 20-theme taxonomy reaches the AI brief. Labels are resolved at
            # render time (build_prompt reads the SAME en themes.json the frontend uses) —
            # the fact layer carries keys + numbers only (C-1, no display labels in payloads).
            summary["sector_performance"] = [
                {"key": s.key, "change_1d": s.change_1d}
                for s in [*sectors.payload.sectors, *sectors.payload.themes]
                if s.change_1d is not None
            ]
        return summary

    # ---- Evidence index ----

    def _build_evidence(
        self,
        risk: RiskEnvelope,
        macro: MacroEnvelope,
        equities: EquitiesEnvelope,
        crypto: CryptoEnvelope,
        news: NewsEnvelope,
        calendar: CalendarEnvelope,
        sectors: SectorsEnvelope | None = None,
    ) -> dict[str, EvidenceRef]:
        index: dict[str, EvidenceRef] = {}
        r = risk.payload

        def add(key: str, dataset: str, path: str, metric: str, value: float | str | None, updated_at: str | None = None) -> None:
            if value is None:
                return
            index[key] = EvidenceRef(
                dataset=dataset, path=path, metric=metric, value=value, updated_at=updated_at or now_utc()
            )

        add("ev_total_score", "risk", "payload.total_score", "total_score", r.total_score, r.generated_at)
        add("ev_confidence", "risk", "payload.confidence", "confidence", r.confidence, r.generated_at)
        add("ev_regime", "risk", "payload.regime", "regime", r.regime, r.generated_at)

        for i, dim in enumerate(r.dimensions):
            for j, ind in enumerate(dim.indicators):
                if ind.value is None:
                    continue
                add(
                    f"ev_{dim.key}_{ind.key}",
                    "risk",
                    f"payload.dimensions[{i}].indicators[{j}].value",
                    ind.key,
                    ind.value,
                    ind.updated_at,
                )

        for group in ("rates", "credit", "inflation", "labor", "liquidity", "fx"):
            for i, ind in enumerate(getattr(macro.payload, group)):
                if ind.value is None:
                    continue
                add(
                    f"ev_macro_{ind.key}",
                    "macro",
                    f"payload.{group}[{i}].value",
                    ind.key,
                    ind.value,
                    ind.updated_at,
                )

        for i, asset in enumerate(equities.payload.assets):
            add(
                f"ev_equity_{asset.symbol.lower()}_price",
                "equities",
                f"payload.assets[{i}].price",
                "price",
                asset.price,
                asset.updated_at,
            )
            add(
                f"ev_equity_{asset.symbol.lower()}_1d",
                "equities",
                f"payload.assets[{i}].change_1d",
                "change_1d",
                asset.change_1d,
                asset.updated_at,
            )

        for i, asset in enumerate(crypto.payload.assets):
            add(f"ev_crypto_{asset.symbol.lower()}_price", "crypto", f"payload.assets[{i}].price", "price", asset.price, asset.updated_at)

        for i, item in enumerate(news.payload.items[:5]):
            add(f"ev_news_{i}", "news", f"payload.items[{i}].importance", "importance", item.importance, item.published_at)

        for i, event in enumerate(calendar.payload.events[:5]):
            add(f"ev_calendar_{i}", "calendar", f"payload.events[{i}].datetime", "event_datetime", event.datetime)

        # #98: sector/theme 1d moves are citable evidence — the AI brief's rule is
        # "may ONLY cite entries present in the evidence_index", so the Sector / theme
        # performance section of the prompt needs refs here or it would be uncitable.
        if sectors is not None:
            for group in ("sectors", "themes"):
                for i, row in enumerate(getattr(sectors.payload, group)):
                    if row.change_1d is None:
                        continue
                    add(
                        f"ev_sector_{row.key}",
                        "sectors",
                        f"payload.{group}[{i}].change_1d",
                        "change_1d",
                        row.change_1d,
                        sectors.generated_at,
                    )
        return index
