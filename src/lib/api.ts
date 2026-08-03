import type { z } from "zod";
import {
  ANALYSIS_SCHEMA,
  DATASET_SCHEMAS,
  type DatasetKey,
  type DatasetSchemaKey,
} from "@/schemas";

/**
 * 前端数据访问接口（架构 §3.6）。
 * 路径规则：
 *   latest/*.json          → data/latest/{key}.json
 *   analysis (lang)        → data/latest/analysis.{lang}.json
 *   history (slice)        → data/history/{key}/{slice}.json
 *   metadata               → data/metadata/{key}.json
 * 所有文件先经 Zod 校验；失败抛 SchemaError → 页面渲染 ErrorState（架构 §8.8）。
 */

export type DatasetOptions = {
  lang?: "zh-CN" | "en";
  slice?: "30d" | "90d" | "daily";
};

export type MetadataKey = "sources" | "freshness" | "schema-version" | "translations";

/** 历史序列 key（架构 §1.7：history/risk/*、history/market/*） */
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
    // 归一化：去掉尾斜杠，如 "/market-risk-dashboard/"
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  /** 构造数据文件 URL（路径规则见文件头注释）。 */
  pathFor(key: DatasetKey | MetadataKey | HistoryKey, opts: DatasetOptions = {}): string {
    if (key === "analysis") {
      const lang = opts.lang ?? "zh-CN";
      return `${this.baseUrl}/data/latest/analysis.${lang}.json`;
    }
    if (key === "sources" || key === "freshness" || key === "schema-version" || key === "translations") {
      return `${this.baseUrl}/data/metadata/${key}.json`;
    }
    if (opts.slice) {
      // history 数据集：data/history/{key}/{slice}.json
      return `${this.baseUrl}/data/history/${key}/${opts.slice}.json`;
    }
    return `${this.baseUrl}/data/latest/${key}.json`;
  }

  private resolveSchema(key: DatasetKey): z.ZodTypeAny {
    if (key === "analysis") return ANALYSIS_SCHEMA;
    if (key in DATASET_SCHEMAS) return DATASET_SCHEMAS[key as DatasetSchemaKey];
    // dashboard 等聚合 schema 随 T04 注册；骨架期显式报错而非静默失败
    throw new SchemaError(key, this.pathFor(key), {
      issues: [{ path: [], message: `No schema registered for key: ${key}` }],
    } as unknown as z.ZodError);
  }

  /**
   * 拉取并校验数据集。
   * - 返回类型：analysis → AnalysisDataset；其余 → Dataset<T>（envelope）。
   * - 可显式传入 schema 覆盖注册表（如 T04 为 dashboard 注册聚合 schema、历史切片/元数据传原始 schema）。
   * - key 类型放宽到 MetadataKey/HistoryKey：仅当显式传 schema 时使用（如 StatusPage 拉元数据），
   *   否则 resolveSchema 只对 DatasetKey 生效。
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

/** 默认客户端单例（T04 hooks/useDataset 复用）。 */
export const datasetClient = new DatasetClient();
