import type { z } from "zod";
import {
  AnalysisDataset,
  CalendarEnvelope,
  CommoditiesEnvelope,
  CryptoEnvelope,
  DashboardEnvelope,
  EquitiesEnvelope,
  FactLayer,
  MacroEnvelope,
  NewsEnvelope,
  RiskEnvelope,
  SectorsEnvelope,
} from "./generated/contracts";

/**
 * The frontend contract surface (#101).
 *
 * Everything re-exported from ./generated is produced by scripts/gen_ts_contracts.py
 * from the pydantic models in pipeline/schemas/. The hand-written Zod mirror that used
 * to live beside this file is gone: two copies of the same contract drifted exactly the
 * way two copies do — the frontend never learned about the `empty` freshness state, and
 * `expected_interval_minutes` was maintained in both config/sources.yaml and
 * src/lib/freshness.ts. Re-syncing them would have bought one release of quiet.
 *
 * Run `npm run gen:contracts` after touching a pydantic model; `npm run check:contracts`
 * fails CI when the checked-in output no longer matches.
 *
 * The only hand-written contracts left are the ones with no pydantic counterpart:
 * history slices (./history), which the pipeline emits as plain arrays.
 */
export * from "./generated/contracts";
export * from "./history";

/**
 * Runtime contract values that are not schemas: the freshness/reason vocabularies, the
 * dataset registry and the expected update intervals. Consumed by src/lib/freshness.ts
 * and scripts/validate-json.mjs so those two stop re-declaring what the pipeline knows.
 */
export { default as CONTRACT_CONSTANTS } from "./generated/constants.json";

/**
 * Dataset schema registry (used by DatasetClient to resolve by key; dataset keys align with the pipeline).
 * analysis is a self-describing contract file (not an envelope) and is handled separately.
 */
export type DatasetSchemaKey =
  | "macro"
  | "equities"
  | "sectors"
  | "crypto"
  | "commodities"
  | "news"
  | "calendar"
  | "risk"
  | "dashboard"
  | "factlayer";

/**
 * Annotated as ZodTypeAny rather than inferred. The generated envelopes are deep enough that
 * `as const` inference blows past what tsc will serialize into a declaration (TS7056), and the
 * only consumer — DatasetClient.resolveSchema — erases to ZodTypeAny anyway. Per-dataset types
 * come from the generated `Dataset`/payload types, not from this lookup table.
 */
export const DATASET_SCHEMAS: Record<DatasetSchemaKey, z.ZodTypeAny> = {
  macro: MacroEnvelope,
  equities: EquitiesEnvelope,
  sectors: SectorsEnvelope,
  crypto: CryptoEnvelope,
  commodities: CommoditiesEnvelope,
  news: NewsEnvelope,
  calendar: CalendarEnvelope,
  risk: RiskEnvelope,
  dashboard: DashboardEnvelope,
  factlayer: FactLayer,
};

/** analysis is a self-describing contract (AnalysisDataset) and does not use the envelope. */
export const ANALYSIS_SCHEMA: z.ZodTypeAny = AnalysisDataset;

/** Dataset key (architecture §3.6; history slices are plain arrays, parsed via the schema override passed as the third fetch argument) */
export type DatasetKey = "dashboard" | DatasetSchemaKey | "analysis";
