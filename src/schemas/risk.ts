import { z } from "zod";
import { EvidenceRef, FreshnessStatus, ProviderProvenance, utcDateTime } from "./envelope";

export const RiskDimensionKey = z.enum([
  "macro",
  "liquidity_credit",
  "equity_structure",
  "volatility",
  "cross_asset",
  "trend",
]);
export const RiskDirection = z.enum(["higher_is_riskier", "lower_is_riskier", "neutral"]);
export const RiskLevel = z.enum([
  "risk_on",
  "low_risk",
  "caution",
  "high_risk",
  "severe_risk",
  "crisis",
]);
export const MarketRegime = z.enum([
  "goldilocks",
  "risk_on",
  "disinflation",
  "reflation",
  "late_cycle",
  "stagflation",
  "liquidity_stress",
  "risk_off",
  "crisis",
]);
export const RiskTrend = z.enum(["rising", "falling", "flat"]);

export const RiskIndicator = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    value: z.number().finite().nullable(),
    percentile: z.number().finite().min(0).max(100).nullable(),
    z_score: z.number().finite().nullable(),
    risk_score: z.number().finite().min(0).max(100),
    direction: RiskDirection,
    weight: z.number().finite().min(0),
    source: z.string().min(1),
    updated_at: utcDateTime.nullable(),
    status: FreshnessStatus,
    is_proxy: z.boolean(),
  })
  .strict();

export const RiskDimension = z
  .object({
    key: RiskDimensionKey,
    label: z.string().min(1),
    weight: z.number().finite().min(0),
    effective_weight: z.number().finite().min(0),
    score: z.number().finite().min(0).max(100),
    indicators: z.array(RiskIndicator),
    coverage: z.number().finite().min(0).max(1),
    trend: RiskTrend,
  })
  .strict();

export const DriverContribution = z
  .object({
    dimension_key: RiskDimensionKey,
    indicator_key: z.string().min(1),
    label: z.string().min(1),
    contribution: z.number().finite(),
    change_1d: z.number().finite().nullable(),
    evidence_ref: EvidenceRef.nullable(),
    is_proxy: z.boolean(),
    discount: z.number().finite().min(0).max(1),
  })
  .strict();

/** Breadth sample disclosure (#69): the ratio plus qualifying/considered counts. */
export const BreadthSnapshot = z
  .object({
    breadth_above_ma200: z.number().finite().min(0).max(1).nullable(),
    breadth_qualifying: z.number().int().min(0),
    breadth_considered: z.number().int().min(0),
    new_highs_ratio: z.number().finite().min(0).max(1).nullable(),
    new_lows_ratio: z.number().finite().min(0).max(1).nullable(),
    new_highs_qualifying: z.number().int().min(0),
    new_lows_qualifying: z.number().int().min(0),
    new_considered: z.number().int().min(0),
    small_cap_relative: z.number().finite().nullable(),
    semis_relative: z.number().finite().nullable(),
    is_proxy: z.boolean(),
    note: z.string(),
  })
  .strict();

export const RiskModelResult = z
  .object({
    model_version: z.string().min(1),
    generated_at: utcDateTime,
    total_score: z.number().finite().min(0).max(100),
    risk_level: RiskLevel,
    trend_1d: z.number().finite().nullable(),
    trend_1w: z.number().finite().nullable(),
    trend_1m: z.number().finite().nullable(),
    dimensions: z.array(RiskDimension),
    top_drivers: z.array(DriverContribution),
    breadth: BreadthSnapshot.nullable(),
    regime: MarketRegime,
    regime_evidence: z.array(z.string()),
    confidence: z.number().finite().min(0).max(1),
    confidence_factors: z.record(z.number().finite()),
    disclaimer: z.string(),
  })
  .strict();

export const RiskEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable(),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    provenance: ProviderProvenance,
    payload: RiskModelResult,
  })
  .strict();

export type RiskDimensionKey = z.infer<typeof RiskDimensionKey>;
export type RiskDirection = z.infer<typeof RiskDirection>;
export type RiskLevel = z.infer<typeof RiskLevel>;
export type MarketRegime = z.infer<typeof MarketRegime>;
export type RiskTrend = z.infer<typeof RiskTrend>;
export type RiskIndicator = z.infer<typeof RiskIndicator>;
export type RiskDimension = z.infer<typeof RiskDimension>;
export type DriverContribution = z.infer<typeof DriverContribution>;
export type RiskModelResult = z.infer<typeof RiskModelResult>;
export type RiskEnvelope = z.infer<typeof RiskEnvelope>;
