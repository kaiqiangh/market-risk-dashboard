import type { FreshnessStatus } from "@/schemas";

/** Global data envelope (architecture §3.1). */
export interface BaseEnvelope {
  generated_at: string;
  schema_version: string;
  source: string | string[];
  source_updated_at: string | null;
  freshness_status: FreshnessStatus;
  data_quality: number;
  payload: Record<string, unknown>;
}

/** Dataset with a strongly typed payload. */
export interface Dataset<T> extends Omit<BaseEnvelope, "payload"> {
  payload: T;
}
