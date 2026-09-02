import type { z } from "zod";
import {
  ANALYSIS_SCHEMA,
  DATASET_SCHEMAS,
  type DatasetKey,
  type DatasetSchemaKey,
} from "@/schemas";
import { collectUnknownFields } from "@/lib/unknownFields";

/**
 * Frontend data access interface (architecture §3.6).
 * Path rules:
 *   latest/*.json          → data/latest/{key}.json
 *   analysis (lang)        → data/latest/analysis.{lang}.json
 *   history (slice)        → data/history/{key}/{slice}.json
 *   metadata               → data/metadata/{key}.json
 * All files are validated with Zod first; on failure throw SchemaError → page renders ErrorState (architecture §8.8).
 */

/** Macro group names (must mirror pipeline/collectors/macro.py SERIES_GROUPS keys, #96). */
export type MacroGroupName = "rates" | "credit" | "volatility" | "inflation" | "labor" | "liquidity" | "fx";

export type DatasetOptions = {
  lang?: "zh-CN" | "en";
  /** History slice: classic per-key slices (risk/market) or the macro per-GROUP bundles
   * (`{group}.30d`/`{group}.90d`, #96/#84 §3) — constrained to real groups. */
  slice?: "30d" | "90d" | "daily" | `${MacroGroupName}.30d` | `${MacroGroupName}.90d`;
};

export type MetadataKey = "sources" | "freshness" | "schema-version" | "translations";

/** Bound every static-data request so a broken Pages edge cannot hold a query forever. */
export const DATA_REQUEST_TIMEOUT_MS = 10_000;

/** History series key (architecture §1.7: history/risk/*, history/market/*).
 * "macro" is the per-GROUP 30d/90d bundle (history/macro/{group}.{slice}.json, #96/#84 §3). */
export type HistoryKey = "market" | "risk" | "macro";

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

/**
 * Datasets already inspected for unknown fields this session (#101).
 *
 * The generated schemas are .passthrough(), so a producer can add a field without
 * breaking a page — which is the point, and also the risk: nobody would ever find out.
 * The first response for each dataset is walked and reported once. Module-level rather
 * than per-client so that a second DatasetClient does not re-log the same drift, and so
 * a page that refetches every 5 minutes logs once, not 288 times a day.
 */
const inspectedForUnknownFields = new Set<string>();

async function fetchWithTimeout(url: string, externalSignal?: AbortSignal): Promise<Response> {
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, DATA_REQUEST_TIMEOUT_MS);
  const abortFromQuery = () => controller.abort(externalSignal?.reason);

  if (externalSignal?.aborted) {
    abortFromQuery();
  } else {
    externalSignal?.addEventListener("abort", abortFromQuery, { once: true });
  }

  try {
    return await fetch(url, { signal: controller.signal });
  } catch (error) {
    if (timedOut) throw new Error(`Data request timed out: ${url}`);
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", abortFromQuery);
  }
}

/** Reset the once-per-session unknown-field guard (tests only). */
export function resetUnknownFieldReports(): void {
  inspectedForUnknownFields.clear();
}

function reportUnknownFields(key: string, url: string, schema: z.ZodTypeAny, json: unknown): void {
  if (inspectedForUnknownFields.has(key)) return;
  // Marked before the walk, not after: the cost is paid once per dataset per session
  // whether or not anything turns up.
  inspectedForUnknownFields.add(key);
  const unknown = collectUnknownFields(schema, json);
  if (unknown.length === 0) return;
  console.warn(
    `[contracts] ${key} carries ${unknown.length} field(s) the schema does not declare ` +
      `(accepted, not dropped): ${unknown.join(", ")} @ ${url}. ` +
      `If the pipeline added them, run \`npm run gen:contracts\`.`,
  );
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
    if (key === "factlayer") {
      return `${this.baseUrl}/data/latest/facts.json`;
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
    signal?: AbortSignal,
  ): Promise<T> {
    const url = this.pathFor(key, opts);
    const response = await fetchWithTimeout(url, signal);
    if (!response.ok) {
      throw new Error(`Data file unreachable: ${url} (HTTP ${response.status})`);
    }
    const json: unknown = await response.json();
    const target = schema ?? this.resolveSchema(key as DatasetKey);
    const parsed = target.safeParse(json);
    if (!parsed.success) {
      throw new SchemaError(key, url, parsed.error);
    }
    reportUnknownFields(String(key), url, target, json);
    return parsed.data as T;
  }
}

/** Default client singleton (reused by T04 hooks/useDataset). */
export const datasetClient = new DatasetClient();
