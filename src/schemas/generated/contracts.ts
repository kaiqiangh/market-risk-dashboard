// ============================================================================
// GENERATED FILE - DO NOT EDIT
//
// Produced by scripts/gen_ts_contracts.py from the pydantic models in
// pipeline/schemas/. Run `npm run gen:contracts` after changing a model;
// `npm run check:contracts` fails CI when this file is out of date.
//
// Schemas are .passthrough(), not .strict(): the pipeline forbids extra fields
// on the way out, and the frontend tolerates them on the way in so that adding
// a field to a dataset cannot take a page down. Unknown fields are reported by
// src/lib/api.ts.
// ============================================================================
/* eslint-disable */
import { z } from "zod";

/** ISO 8601 UTC + Z timestamp, e.g. 2026-08-03T10:00:00Z. */
export const utcDateTime = z.string().datetime();

// ---- Enumerations (Literal aliases in pipeline/schemas/) ----

export const AnalysisLanguage = z.enum(["zh-CN", "en"]);
export type AnalysisLanguage = z.infer<typeof AnalysisLanguage>;

export const CryptoSentiment = z.enum(["risk_on", "risk_off", "neutral"]);
export type CryptoSentiment = z.infer<typeof CryptoSentiment>;

export const EventImportance = z.enum(["high", "medium", "low"]);
export type EventImportance = z.infer<typeof EventImportance>;

export const EventType = z.enum(["economic", "earnings"]);
export type EventType = z.infer<typeof EventType>;

export const FreshnessStatus = z.enum(["fresh", "delayed", "stale", "empty", "missing", "degraded"]);
export type FreshnessStatus = z.infer<typeof FreshnessStatus>;

export const MacroUnit = z.enum(["pct", "bps", "index", "usd", "ratio", "level"]);
export type MacroUnit = z.infer<typeof MacroUnit>;

export const Market = z.enum(["US", "CN", "KR", "HK"]);
export type Market = z.infer<typeof Market>;

export const MarketRegime = z.enum(["goldilocks", "risk_on", "disinflation", "reflation", "late_cycle", "stagflation", "liquidity_stress", "risk_off", "crisis", "indeterminate"]);
export type MarketRegime = z.infer<typeof MarketRegime>;

export const NewsSentiment = z.enum(["positive", "negative", "neutral"]);
export type NewsSentiment = z.infer<typeof NewsSentiment>;

export const NewsSourceLang = z.enum(["en", "zh"]);
export type NewsSourceLang = z.infer<typeof NewsSourceLang>;

export const ReasonCode = z.enum(["ok", "no_rows_returned", "no_events_in_window", "provider_http_error", "provider_rate_limited", "provider_auth_failed", "provider_parse_error", "served_from_fallback", "served_from_cache", "cache_expired", "cache_invalid", "all_providers_failed", "not_collected_this_run", "interval_exceeded", "input_dataset_unhealthy"]);
export type ReasonCode = z.infer<typeof ReasonCode>;

export const RiskDimensionKey = z.enum(["macro", "liquidity_credit", "equity_structure", "volatility", "cross_asset", "trend"]);
export type RiskDimensionKey = z.infer<typeof RiskDimensionKey>;

export const RiskDirection = z.enum(["higher_is_riskier", "lower_is_riskier", "neutral"]);
export type RiskDirection = z.infer<typeof RiskDirection>;

export const RiskLevel = z.enum(["risk_on", "low_risk", "caution", "high_risk", "severe_risk", "crisis"]);
export type RiskLevel = z.infer<typeof RiskLevel>;

export const RiskTrend = z.enum(["rising", "falling", "flat"]);
export type RiskTrend = z.infer<typeof RiskTrend>;


// ---- Models ----

/** The fact-layer and bilingual-pair identity consumed by one AI brief. */
export const AnalysisLineage = z
  .object({
    fact_generation_id: z.string().min(71).regex(new RegExp("^sha256:[0-9a-f]{64}$")),
    fact_generated_at: utcDateTime,
    input_freshness: z.record(FreshnessStatus).default({}),
    pair_id: z.string().min(1).max(128),
  })
  .passthrough();
export type AnalysisLineage = z.infer<typeof AnalysisLineage>;

/** A single piece of evidence that can be cited by the AI. */
export const EvidenceRef = z
  .object({
    dataset: z.string().min(1),
    path: z.string().min(1),
    metric: z.string().min(1),
    value: z.union([z.number().finite(), z.string()]),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type EvidenceRef = z.infer<typeof EvidenceRef>;

/** A scenario (bull/base/bear) statement. */
export const CaseStatement = z
  .object({
    title: z.string().min(1),
    points: z.array(z.string()).default([]),
    evidence_refs: z.array(EvidenceRef).default([]),
  })
  .passthrough();
export type CaseStatement = z.infer<typeof CaseStatement>;

/** A claim with evidence. */
export const SignalClaim = z
  .object({
    claim: z.string().min(1),
    evidence_refs: z.array(EvidenceRef).default([]),
  })
  .passthrough();
export type SignalClaim = z.infer<typeof SignalClaim>;

/** AI bilingual briefing (single-language file). */
export const AnalysisDataset = z
  .object({
    schema_version: z.string().min(1),
    generated_at: utcDateTime,
    language: AnalysisLanguage,
    market_state: z.string().min(1),
    market_regime: z.string().min(1),
    summary: z.string().min(1),
    top_risk_drivers: z.array(SignalClaim).default([]),
    supporting_signals: z.array(SignalClaim).default([]),
    contradicting_signals: z.array(SignalClaim).default([]),
    what_changed_today: z.array(z.string()).default([]),
    watch_next: z.array(z.string()).default([]),
    bull_case: CaseStatement,
    base_case: CaseStatement,
    bear_case: CaseStatement,
    confidence: z.number().finite().min(0).max(1),
    evidence_refs: z.array(EvidenceRef).default([]),
    lineage: AnalysisLineage.nullable().default(null),
    data_freshness: FreshnessStatus.default("degraded"),
  })
  .passthrough();
export type AnalysisDataset = z.infer<typeof AnalysisDataset>;

/** Which provider actually served the dataset (#65, ADR 0004). The resolved provider (not the candidate list), whether that was a fallback, and whether the value came from the last-good cache. Cache replay is deliberately partial until #66: the cache entry does not record the originating provider, so `provider` is "last-good". */
export const ProviderProvenance = z
  .object({
    provider: z.string().min(1),
    used_fallback: z.boolean().default(false),
    from_cache: z.boolean().default(false),
  })
  .passthrough();
export type ProviderProvenance = z.infer<typeof ProviderProvenance>;

/** Global data envelope (architecture §3.1). payload is the business data; each dataset model overrides the payload type in a subclass for strong validation (e.g. MacroEnvelope(payload: MacroDataset)). */
export const BaseEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: z.record(z.unknown()),
  })
  .passthrough();
export type BaseEnvelope = z.infer<typeof BaseEnvelope>;

/** Breadth sample disclosure (#69): the ratio plus the qualifying/considered counts. A thinning sample (4 of 18 constituents vs 18 of 18) is visible in the published data, not hidden behind a confidently-stated ratio. */
export const BreadthSnapshot = z
  .object({
    breadth_above_ma200: z.number().finite().min(0).max(1).nullable().default(null),
    breadth_qualifying: z.number().int().min(0).default(0),
    breadth_considered: z.number().int().min(0).default(0),
    new_highs_ratio: z.number().finite().min(0).max(1).nullable().default(null),
    new_lows_ratio: z.number().finite().min(0).max(1).nullable().default(null),
    new_highs_qualifying: z.number().int().min(0).default(0),
    new_lows_qualifying: z.number().int().min(0).default(0),
    new_considered: z.number().int().min(0).default(0),
    small_cap_relative: z.number().finite().nullable().default(null),
    semis_relative: z.number().finite().nullable().default(null),
    is_proxy: z.boolean().default(true),
    note: z.string().min(0).default(""),
  })
  .passthrough();
export type BreadthSnapshot = z.infer<typeof BreadthSnapshot>;

export const CalendarEvent = z
  .object({
    id: z.string().min(1),
    type: EventType,
    title: z.string().min(1),
    country: z.string().nullable().default(null),
    datetime: utcDateTime,
    importance: EventImportance.default("medium"),
    actual: z.number().finite().nullable().default(null),
    forecast: z.number().finite().nullable().default(null),
    previous: z.number().finite().nullable().default(null),
    unit: z.string().nullable().default(null),
    related_assets: z.array(z.string()).default([]),
    source: z.string().min(1),
  })
  .passthrough();
export type CalendarEvent = z.infer<typeof CalendarEvent>;

/** calendar.json payload. */
export const CalendarDataset = z
  .object({
    events: z.array(CalendarEvent).default([]),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type CalendarDataset = z.infer<typeof CalendarDataset>;

export const CalendarEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: CalendarDataset,
  })
  .passthrough();
export type CalendarEnvelope = z.infer<typeof CalendarEnvelope>;

export const CommodityAsset = z
  .object({
    symbol: z.string().min(1),
    name: z.string().min(1),
    name_zh: z.string().nullable().default(null),
    price: z.number().finite(),
    currency: z.string().default("USD"),
    change_1d: z.number().finite().nullable().default(null),
    change_1w: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    source: z.string().min(1),
    updated_at: utcDateTime,
  })
  .passthrough();
export type CommodityAsset = z.infer<typeof CommodityAsset>;

/** commodities.json payload. */
export const CommoditiesDataset = z
  .object({
    assets: z.array(CommodityAsset).default([]),
  })
  .passthrough();
export type CommoditiesDataset = z.infer<typeof CommoditiesDataset>;

export const CommoditiesEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: CommoditiesDataset,
  })
  .passthrough();
export type CommoditiesEnvelope = z.infer<typeof CommoditiesEnvelope>;

export const CryptoAsset = z
  .object({
    symbol: z.string().min(1),
    name: z.string().min(1),
    price: z.number().finite(),
    change_1d: z.number().finite().nullable().default(null),
    change_1w: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    market_cap: z.number().finite().nullable().default(null),
    volume_24h: z.number().finite().nullable().default(null),
    source: z.string().min(1),
    updated_at: utcDateTime,
  })
  .passthrough();
export type CryptoAsset = z.infer<typeof CryptoAsset>;

/** crypto.json payload. */
export const CryptoDataset = z
  .object({
    assets: z.array(CryptoAsset).default([]),
    btc_dominance: z.number().finite().min(0).max(1).nullable().default(null),
    stablecoin_mcap: z.number().finite().nullable().default(null),
    market_cap_total: z.number().finite().nullable().default(null),
    sentiment: CryptoSentiment.nullable().default(null),
  })
  .passthrough();
export type CryptoDataset = z.infer<typeof CryptoDataset>;

export const CryptoEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: CryptoDataset,
  })
  .passthrough();
export type CryptoEnvelope = z.infer<typeof CryptoEnvelope>;

/** Cross-asset confirmation signal entry (equity/crypto etc.). */
export const DashboardAsset = z
  .object({
    asset: z.string().min(1),
    category: z.string().min(1),
    change_1d: z.number().finite().nullable().default(null),
  })
  .passthrough();
export type DashboardAsset = z.infer<typeof DashboardAsset>;

/** Top driver: contribution to the total score (weight × risk score). */
export const DriverContribution = z
  .object({
    dimension_key: RiskDimensionKey,
    indicator_key: z.string().min(1),
    label: z.string().min(1),
    contribution: z.number().finite(),
    change_1d: z.number().finite().nullable().default(null),
    evidence_ref: EvidenceRef.nullable().default(null),
    is_proxy: z.boolean(),
    discount: z.number().finite().min(0).max(1).default(1.0),
  })
  .passthrough();
export type DriverContribution = z.infer<typeof DriverContribution>;

/** Sub-indicator: raw value + 5Y percentile + mapped risk score. */
export const RiskIndicator = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    value: z.number().finite().nullable().default(null),
    percentile: z.number().finite().min(0).max(100).nullable().default(null),
    z_score: z.number().finite().nullable().default(null),
    risk_score: z.number().finite().min(0).max(100),
    direction: RiskDirection.default("neutral"),
    weight: z.number().finite().min(0).default(0.0),
    source: z.string().min(1),
    updated_at: utcDateTime.nullable().default(null),
    status: FreshnessStatus.default("fresh"),
    is_proxy: z.boolean(),
  })
  .passthrough();
export type RiskIndicator = z.infer<typeof RiskIndicator>;

/** Risk dimension (one of the 6). */
export const RiskDimension = z
  .object({
    key: RiskDimensionKey,
    label: z.string().min(1),
    weight: z.number().finite().min(0),
    effective_weight: z.number().finite().min(0),
    score: z.number().finite().min(0).max(100),
    indicators: z.array(RiskIndicator).default([]),
    coverage: z.number().finite().min(0).max(1),
    trend: RiskTrend.default("flat"),
  })
  .passthrough();
export type RiskDimension = z.infer<typeof RiskDimension>;

/** Risk model output (risk.json payload, also embedded in facts.json). */
export const RiskModelResult = z
  .object({
    model_version: z.string().min(1),
    generated_at: utcDateTime,
    total_score: z.number().finite().min(0).max(100),
    risk_level: RiskLevel,
    trend_1d: z.number().finite().nullable().default(null),
    trend_1w: z.number().finite().nullable().default(null),
    trend_1m: z.number().finite().nullable().default(null),
    dimensions: z.array(RiskDimension).default([]),
    top_drivers: z.array(DriverContribution).default([]),
    breadth: BreadthSnapshot.nullable(),
    regime: MarketRegime,
    regime_evidence: z.array(z.string()).default([]),
    confidence: z.number().finite().min(0).max(1),
    confidence_factors: z.record(z.number().finite()).default({}),
    disclaimer: z.string().default("This indicator is a modeled estimate of market stress based on historical data and current market signals. It is not a definitive probability or investment advice."),
  })
  .passthrough();
export type RiskModelResult = z.infer<typeof RiskModelResult>;

/** dashboard.json payload (consistent with the frontend Zod strict structure). */
export const DashboardPayload = z
  .object({
    risk: RiskModelResult,
    regime: MarketRegime,
    top_drivers: z.array(DriverContribution).default([]),
    cross_asset: z.array(DashboardAsset).default([]),
    catalysts: z.array(z.record(z.unknown())).default([]),
    sector_performance: z.array(z.record(z.unknown())).default([]),
  })
  .passthrough();
export type DashboardPayload = z.infer<typeof DashboardPayload>;

/** dashboard.json envelope (strongly typed payload). */
export const DashboardEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: DashboardPayload,
  })
  .passthrough();
export type DashboardEnvelope = z.infer<typeof DashboardEnvelope>;

/** Why a dataset carries the freshness status it carries (#89). Replaces the free-text ``reason`` string that produced eight datasets all saying the literal word "degraded". ``code`` is machine-readable and drawn from the closed :data:`ReasonCode` vocabulary; the UI translates it. ``detail`` is human-readable **English only** and is deliberately not translated: its audience is the operator and the next agent, and keeping it monolingual is what makes the translated surface finite. ``detail`` is also the only field here that can ever carry provider text, so it is the sole input to the redactor (#92). */
export const FreshnessReason = z
  .object({
    code: ReasonCode,
    detail: z.string().max(200).default(""),
  })
  .passthrough();
export type FreshnessReason = z.infer<typeof FreshnessReason>;

/** One dataset's entry in ``metadata/freshness.json``. Every registered dataset appears on every run — including the ones that failed. An absent key used to mean "healthy, nothing to report" by accident; it now cannot happen, because the projection iterates the registry rather than the datasets that happened to succeed. */
export const DatasetFreshness = z
  .object({
    status: FreshnessStatus,
    reason: FreshnessReason,
    updated_at: utcDateTime,
  })
  .passthrough();
export type DatasetFreshness = z.infer<typeof DatasetFreshness>;

/** One resolved provider and the datasets it served for a domain. */
export const ProviderResolution = z
  .object({
    provider: z.string().min(1),
    datasets: z.array(z.string()).default([]),
    used_fallback: z.boolean().default(false),
    from_cache: z.boolean().default(false),
  })
  .passthrough();
export type ProviderResolution = z.infer<typeof ProviderResolution>;

/** One provider domain's entry in ``metadata/sources.json``. ``degraded`` is derived from the outcomes of the datasets this domain serves, never set independently — see :meth:`~pipeline.storage.outcomes.RunOutcomes.sources_projection`. Unlike every other contract in this package this model permits extra fields. Provider metadata is provider-specific and additive (``sources`` for the RSS fan-out, ``error`` for a failed call, cache diagnostics), and forbidding it would mean either dropping real operational detail on the floor or bumping the schema every time a provider learns to report something new. The *derived* fields below are the contract; the rest is passthrough. */
export const DomainStatus = z
  .object({
    degraded: z.boolean().default(false),
    status: FreshnessStatus.default("missing"),
    reason: FreshnessReason,
    datasets: z.array(z.string()).default([]),
    provider: z.string().nullable().default(null),
    providers: z.array(ProviderResolution).default([]),
  })
  .passthrough();
export type DomainStatus = z.infer<typeof DomainStatus>;

/** Card-level data of a single equity. */
export const EquityAsset = z
  .object({
    symbol: z.string().min(1),
    name: z.string().min(1),
    name_zh: z.string().nullable().default(null),
    market: Market.default("US"),
    sector: z.string().default("other"),
    theme: z.array(z.string()).default([]),
    price: z.number().finite(),
    currency: z.string().default("USD"),
    change_1d: z.number().finite().nullable().default(null),
    change_1w: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    change_ytd: z.number().finite().nullable().default(null),
    volume: z.number().finite().nullable().default(null),
    market_cap: z.number().finite().nullable().default(null),
    ma50_distance_pct: z.number().finite().nullable().default(null),
    ma200_distance_pct: z.number().finite().nullable().default(null),
    rsi14: z.number().finite().min(0).max(100).nullable().default(null),
    percentile_1y: z.number().finite().min(0).max(100).nullable().default(null),
    percentile_1y_obs: z.number().int().min(0).default(0),
    source: z.string().min(1),
    updated_at: utcDateTime,
    is_proxy: z.boolean().default(false),
  })
  .passthrough();
export type EquityAsset = z.infer<typeof EquityAsset>;

/** equities.json payload. */
export const EquitiesDataset = z
  .object({
    assets: z.array(EquityAsset).default([]),
  })
  .passthrough();
export type EquitiesDataset = z.infer<typeof EquitiesDataset>;

export const EquitiesEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: EquitiesDataset,
  })
  .passthrough();
export type EquitiesEnvelope = z.infer<typeof EquitiesEnvelope>;

/** Fact layer (facts.json). */
export const FactLayer = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    generation_id: z.string().min(71).regex(new RegExp("^sha256:[0-9a-f]{64}$")).nullable().default(null),
    data_freshness: z.record(FreshnessStatus).default({}),
    risk: RiskModelResult,
    macro_summary: z.record(z.unknown()).default({}),
    market_summary: z.record(z.unknown()).default({}),
    news_top: z.array(z.record(z.unknown())).default([]),
    calendar_next7d: z.array(z.record(z.unknown())).default([]),
    evidence_index: z.record(EvidenceRef).default({}),
  })
  .passthrough();
export type FactLayer = z.infer<typeof FactLayer>;

/** Probability of a target rate bucket (0-1). */
export const FedWatchRateProb = z
  .object({
    target_rate: z.number().finite(),
    probability: z.number().finite().min(0).max(1),
    change_1d: z.number().finite().nullable().default(null),
  })
  .passthrough();
export type FedWatchRateProb = z.infer<typeof FedWatchRateProb>;

/** CME FedWatch probability self-computed snapshot (architecture §1.6 frozen methodology). */
export const FedWatchSnapshot = z
  .object({
    meeting_date: utcDateTime.nullable().default(null),
    effective_rate: z.number().finite(),
    implied_rate: z.number().finite(),
    probabilities: z.array(FedWatchRateProb).default([]),
    inferred_action: z.enum(["hold", "hike", "cut", "insufficient_data"]).nullable().default(null),
    change_1d: z.record(z.number().finite()).nullable().default(null),
    status: z.enum(["accumulating", "ready"]).default("accumulating"),
  })
  .passthrough();
export type FedWatchSnapshot = z.infer<typeof FedWatchSnapshot>;

/** ``metadata/freshness.json`` — the per-dataset freshness record. */
export const FreshnessDocument = z
  .object({
    schema_version: z.string().min(1),
    updated_at: utcDateTime,
    datasets: z.record(DatasetFreshness).default({}),
  })
  .passthrough();
export type FreshnessDocument = z.infer<typeof FreshnessDocument>;

/** A single macro indicator (raw numeric storage, architecture §8.3). */
export const MacroIndicator = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    value: z.number().finite().nullable().default(null),
    previous: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    unit: MacroUnit.default("level"),
    source: z.string().min(1),
    updated_at: utcDateTime.nullable().default(null),
    status: FreshnessStatus.default("fresh"),
  })
  .passthrough();
export type MacroIndicator = z.infer<typeof MacroIndicator>;

/** Macro dataset payload. */
export const MacroDataset = z
  .object({
    rates: z.array(MacroIndicator).default([]),
    credit: z.array(MacroIndicator).default([]),
    volatility: z.array(MacroIndicator).default([]),
    inflation: z.array(MacroIndicator).default([]),
    labor: z.array(MacroIndicator).default([]),
    liquidity: z.array(MacroIndicator).default([]),
    fx: z.array(MacroIndicator).default([]),
    fedwatch: FedWatchSnapshot.nullable().default(null),
  })
  .passthrough();
export type MacroDataset = z.infer<typeof MacroDataset>;

/** macro.json envelope (strongly typed payload). */
export const MacroEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: MacroDataset,
  })
  .passthrough();
export type MacroEnvelope = z.infer<typeof MacroEnvelope>;

/** Memory cycle proxy (review P0-1: MVP uses Micron/Hynix/Samsung share prices as a memory cycle proxy). */
export const MemoryProxy = z
  .object({
    label: z.string().min(1),
    label_zh: z.string().nullable().default(null),
    change_1w: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    note: z.string().nullable().default(null),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type MemoryProxy = z.infer<typeof MemoryProxy>;

export const NewsItem = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1),
    title_zh: z.string().nullable().default(null),
    lang: NewsSourceLang.default("en"),
    source: z.string().min(1),
    url: z.string().min(1),
    published_at: utcDateTime,
    categories: z.array(z.string()).default([]),
    assets: z.array(z.string()).default([]),
    importance: z.number().finite().min(0).max(100),
    sentiment: NewsSentiment.nullable().default(null),
    summary: z.string().default(""),
    summary_zh: z.string().nullable().default(null),
    impact_window: z.string().nullable().default(null),
  })
  .passthrough();
export type NewsItem = z.infer<typeof NewsItem>;

/** news.json payload. */
export const NewsDataset = z
  .object({
    items: z.array(NewsItem).default([]),
    total: z.number().int().min(0).default(0),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type NewsDataset = z.infer<typeof NewsDataset>;

export const NewsEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: NewsDataset,
  })
  .passthrough();
export type NewsEnvelope = z.infer<typeof NewsEnvelope>;

/** Symmetric full-pair translation of a news item (AI automation produces news.zh-translations.json, ADR-0003). Carries both English (title/summary) and Chinese (title_zh/summary_zh) for the same id; merge copies both sides without overwriting the canonical English (title/summary) of the item. */
export const NewsTranslation = z
  .object({
    id: z.string().min(1),
    title: z.string().nullable().default(null),
    summary: z.string().nullable().default(null),
    title_zh: z.string().min(1),
    summary_zh: z.string().nullable().default(null),
  })
  .passthrough();
export type NewsTranslation = z.infer<typeof NewsTranslation>;

/** news.zh-translations.json (architecture §1.5: merged into news.json on the next pipeline run). */
export const NewsTranslationsDataset = z
  .object({
    items: z.array(NewsTranslation).default([]),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type NewsTranslationsDataset = z.infer<typeof NewsTranslationsDataset>;

/** risk.json envelope (payload is RiskModelResult, consistent with the embedded fact layer structure). Inherits the base envelope shape (#64): freshness_status is required with no default, so the risk card cannot certify itself as fresh — the only producer is finalize_freshness. */
export const RiskEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: RiskModelResult,
  })
  .passthrough();
export type RiskEnvelope = z.infer<typeof RiskEnvelope>;

/** Sector or theme entry. No ``label``/``label_zh``: display labels live in ``src/i18n/locales/{en,zh-CN}/themes.json``, keyed by ``key`` (C-1/#102). The payload carries the key and the numbers; the frontend renders ``t(themes.<key>)`` and ``check:i18n`` catches a key with no Chinese label. ``constituents`` (themes only, #93) lists the theme's member symbols from ``config/themes.yaml`` — published so the Themes page can render them without a second data source. ``percentile_1y`` is the theme series' trailing-20-session return ranked in its trailing-252-session window (#86 §4); ``None`` with ``percentile_1y_obs`` below the configured minimum is "warming up", not "missing". */
export const SectorItem = z
  .object({
    key: z.string().min(1),
    change_1d: z.number().finite().nullable().default(null),
    change_1w: z.number().finite().nullable().default(null),
    change_1m: z.number().finite().nullable().default(null),
    percentile_1y: z.number().finite().min(0).max(100).nullable().default(null),
    percentile_1y_obs: z.number().int().min(0).default(0),
    constituents: z.array(z.string()).default([]),
    updated_at: utcDateTime.nullable().default(null),
  })
  .passthrough();
export type SectorItem = z.infer<typeof SectorItem>;

/** sectors.json payload. */
export const SectorsDataset = z
  .object({
    sectors: z.array(SectorItem).default([]),
    themes: z.array(SectorItem).default([]),
    memory: MemoryProxy.nullable().default(null),
  })
  .passthrough();
export type SectorsDataset = z.infer<typeof SectorsDataset>;

export const SectorsEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable().default(null),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: SectorsDataset,
  })
  .passthrough();
export type SectorsEnvelope = z.infer<typeof SectorsEnvelope>;

/** ``metadata/sources.json`` — the per-provider-domain health record. */
export const SourcesDocument = z
  .object({
    schema_version: z.string().min(1),
    updated_at: utcDateTime,
    domains: z.record(DomainStatus).default({}),
  })
  .passthrough();
export type SourcesDocument = z.infer<typeof SourcesDocument>;
