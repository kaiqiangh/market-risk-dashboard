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
 * 数据集 schema 注册表（供 DatasetClient 按 key 解析；数据集 key 与 pipeline 对齐）。
 * analysis 为自描述契约文件（非 envelope），单独处理。
 * dashboard 为首页聚合（T04 注册；管道在 T05 产出 dashboard.json）。
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

/** analysis 为自描述契约（AnalysisDataset），不走 envelope。 */
export const ANALYSIS_SCHEMA = AnalysisDatasetSchema;

/** 数据集 key（架构 §3.6；历史切片为纯数组，经 fetch 第三参 schema 覆盖解析） */
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
