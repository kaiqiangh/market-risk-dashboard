import { AnalysisDataset as AnalysisDatasetSchema } from "./analysis";
import { CalendarEnvelope } from "./calendar";
import { CryptoEnvelope } from "./crypto";
import { DashboardEnvelope } from "./dashboard";
import { EquitiesEnvelope } from "./equities";
import { MacroEnvelope } from "./macro";
import { NewsEnvelope } from "./news";
import { RiskEnvelope } from "./risk";
import { SectorsEnvelope } from "./sectors";

/**
 * Dataset schema registry (used by DatasetClient to resolve by key; dataset keys align with the pipeline).
 * analysis is a self-describing contract file (not an envelope) and is handled separately.
 * dashboard is the homepage aggregation (registered in T04; the pipeline produces dashboard.json in T05).
 */
export const DATASET_SCHEMAS = {
  macro: MacroEnvelope,
  equities: EquitiesEnvelope,
  sectors: SectorsEnvelope,
  crypto: CryptoEnvelope,
  news: NewsEnvelope,
  calendar: CalendarEnvelope,
  risk: RiskEnvelope,
  dashboard: DashboardEnvelope,
} as const;

export type DatasetSchemaKey = keyof typeof DATASET_SCHEMAS;

/** analysis is a self-describing contract (AnalysisDataset) and does not use the envelope. */
export const ANALYSIS_SCHEMA = AnalysisDatasetSchema;

/** Dataset key (architecture §3.6; history slices are plain arrays, parsed via the schema override passed as the third fetch argument) */
export type DatasetKey = "dashboard" | DatasetSchemaKey | "analysis";

export type { AnalysisDataset, CaseStatement, SignalClaim } from "./analysis";
export type { CalendarDataset, CalendarEnvelope, CalendarEvent, EventImportance, EventType } from "./calendar";
export type { CryptoAsset, CryptoDataset, CryptoEnvelope, CryptoSentiment } from "./crypto";
export type { DashboardPayload, DashboardEnvelope } from "./dashboard";
export type { EquitiesDataset, EquitiesEnvelope, EquityAsset, Market } from "./equities";
export type { BaseEnvelope, EvidenceRef, FreshnessStatus } from "./envelope";
export type { FactLayer } from "./factlayer";
export type {
  MarketSlice,
  MarketSlicePoint,
  RiskTrendPoint,
  RiskTrendSlice,
} from "./history";
export type { FedWatchRateProb, FedWatchSnapshot, MacroDataset, MacroEnvelope, MacroIndicator, MacroUnit } from "./macro";
export type { NewsDataset, NewsEnvelope, NewsItem, NewsSentiment, NewsTranslation, NewsTranslationsDataset } from "./news";
export type {
  DriverContribution,
  MarketRegime,
  RiskDimension,
  RiskDimensionKey,
  RiskDirection,
  RiskEnvelope,
  RiskIndicator,
  RiskLevel,
  RiskModelResult,
  RiskTrend,
} from "./risk";
export type { MemoryProxy, SectorItem, SectorsDataset, SectorsEnvelope } from "./sectors";
