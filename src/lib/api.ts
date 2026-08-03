import type { z } from "zod";
import {
  ANALYSIS_SCHEMA,
  DATASET_SCHEMAS,
  type DatasetKey,
  type DatasetSchemaKey,
} from "@/schemas";

/**
 * Frontend data access interface (architecture §3.6).
 * Path rules:
 *   latest/*.json          → data/latest/{key}.json
 *   analysis (lang)        → data/latest/analysis.{lang}.json
 *   history (slice)        → data/history/{key}/{slice}.json
 *   metadata               → data/metadata/{key}.json
 * All files are validated with Zod first; on failure throw SchemaError → page renders ErrorState (architecture §8.8).
 */

export type DatasetOptions = {
  lang?: "zh-CN" | "en";
  slice?: "30d" | "90d" | "daily";
};

export type MetadataKey = "sources" | "freshness" | "schema-version" | "translations";

/** History series key (architecture §1.7: history/risk/*, history/market/*) */
export type HistoryKey = "market" | "risk";

export class SchemaError extends Error {
  readonly key: string;
  readonly url: string;
  readonly issues: string[];

  constructor(key: string, url: string, error: z.ZodError) {
    const issues = error.issues.map((issue) => `${issue.path.join(".")}: ${issue.message}`);
    super(`Schema validation failed (${key}) @ ${url}\n${issues.join("\n")}`);
    this.name = "SchemaError";
    this.key = key;
    this.url = url;
    this.issues = issues;
  }
}

export class DatasetClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = import.meta.env.BASE_URL) {
    // Normalize: strip the trailing slash, e.g. "/market-risk-dashboard/"
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  /** Build the data file URL (see the header comment for path rules). */
  pathFor(key: DatasetKey | MetadataKey | HistoryKey, opts: DatasetOptions = {}): string {
    if (key === "analysis") {
      const lang = opts.lang ?? "en";
      return `${this.baseUrl}/data/latest/analysis.${lang}.json`;
    }
    if (key === "sources" || key === "freshness" || key === "schema-version" || key === "translations") {
      return `${this.baseUrl}/data/metadata/${key}.json`;
    }
    if (opts.slice) {
      // history datasets: data/history/{key}/{slice}.json
      return `${this.baseUrl}/data/history/${key}/${opts.slice}.json`;
    }
    return `${this.baseUrl}/data/latest/${key}.json`;
  }

  private resolveSchema(key: DatasetKey): z.ZodTypeAny {
    if (key === "analysis") return ANALYSIS_SCHEMA;
    if (key in DATASET_SCHEMAS) return DATASET_SCHEMAS[key as DatasetSchemaKey];
    // Aggregation schemas like dashboard are registered in T04; fail explicitly during the skeleton phase rather than silently
    throw new SchemaError(key, this.pathFor(key), {
      issues: [{ path: [], message: `No schema registered for key: ${key}` }],
    } as unknown as z.ZodError);
  }

  /**
   * Fetch and validate a dataset.
   * - Return type: analysis → AnalysisDataset; others → Dataset<T> (envelope).
   * - A schema may be explicitly passed to override the registry (e.g. T04 registers the aggregation schema for dashboard; history slices / metadata pass raw schemas).
   * - The key type is widened to MetadataKey/HistoryKey: only used when a schema is explicitly passed (e.g. StatusPage fetching metadata);
   *   otherwise resolveSchema only applies to DatasetKey.
   */
  async fetch<T>(
    key: DatasetKey | MetadataKey | HistoryKey,
    opts: DatasetOptions = {},
    schema?: z.ZodTypeAny,
  ): Promise<T> {
    const url = this.pathFor(key, opts);
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Data file unreachable: ${url} (HTTP ${response.status})`);
    }
    const json: unknown = await response.json();
    const target = schema ?? this.resolveSchema(key as DatasetKey);
    const parsed = target.safeParse(json);
    if (!parsed.success) {
      throw new SchemaError(key, url, parsed.error);
    }
    return parsed.data as T;
  }
}

/** Default client singleton (reused by T04 hooks/useDataset). */
export const datasetClient = new DatasetClient();
