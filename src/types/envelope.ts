import type { FreshnessStatus } from "@/schemas/envelope";

/** 全局数据信封（架构 §3.1）。 */
export interface BaseEnvelope {
  generated_at: string;
  schema_version: string;
  source: string | string[];
  source_updated_at: string | null;
  freshness_status: FreshnessStatus;
  data_quality: number;
  payload: Record<string, unknown>;
}

/** 带强类型 payload 的数据集。 */
export interface Dataset<T> extends Omit<BaseEnvelope, "payload"> {
  payload: T;
}
