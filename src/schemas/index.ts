import { AnalysisDataset as AnalysisDatasetSchema } from "./analysis";
import { CalendarEnvelope } from "./calendar";
import { CryptoEnvelope } from "./crypto";
import { EquitiesEnvelope } from "./equities";
import { MacroEnvelope } from "./macro";
import { NewsEnvelope } from "./news";
import { RiskEnvelope } from "./risk";
import { SectorsEnvelope } from "./sectors";

/**
 * 数据集 schema 注册表（供 DatasetClient 按 key 解析；数据集 key 与 pipeline 对齐）。
 * analysis 为自描述契约文件（非 envelope），单独处理。
 */
export const DATASET_SCHEMAS = {
  macro: MacroEnvelope,
  equities: EquitiesEnvelope,
  sectors: SectorsEnvelope,
  crypto: CryptoEnvelope,
  news: NewsEnvelope,
  calendar: CalendarEnvelope,
  risk: RiskEnvelope,
} as const;

export type DatasetSchemaKey = keyof typeof DATASET_SCHEMAS;

/** analysis 为自描述契约（AnalysisDataset），不走 envelope。 */
export const ANALYSIS_SCHEMA = AnalysisDatasetSchema;

/** 数据集 key（架构 §3.6；dashboard 的专属 schema 在 T04 随首页聚合定义） */
export type DatasetKey = "dashboard" | DatasetSchemaKey | "analysis";

export type { AnalysisDataset, CaseStatement, SignalClaim } from "./analysis";
export type { CalendarDataset, CalendarEvent, EventImportance, EventType } from "./calendar";
export type { CryptoAsset, CryptoDataset, CryptoSentiment } from "./crypto";
export type { EquitiesDataset, EquityAsset, Market } from "./equities";
export type { BaseEnvelope, EvidenceRef, FreshnessStatus } from "./envelope";
export type { FactLayer } from "./factlayer";
export type { FedWatchRateProb, FedWatchSnapshot, MacroDataset, MacroIndicator, MacroUnit } from "./macro";
export type { NewsDataset, NewsItem, NewsSentiment, NewsTranslation, NewsTranslationsDataset } from "./news";
export type {
  DriverContribution,
  MarketRegime,
  RiskDimension,
  RiskDimensionKey,
  RiskDirection,
  RiskIndicator,
  RiskLevel,
  RiskModelResult,
  RiskTrend,
} from "./risk";
export type { MemoryProxy, SectorItem, SectorsDataset } from "./sectors";
