import { z } from "zod";

/**
 * 全局数据 Envelope（架构 §3.1，与 pipeline/schemas/envelope.py 同构）。
 * - strict()：禁止隐式字段（additionalProperties=false 同构）
 * - finite()：拒绝 NaN/Infinity
 * - datetime()：ISO 8601 UTC + Z
 */

export const FreshnessStatus = z.enum(["fresh", "delayed", "stale", "missing", "degraded"]);
export type FreshnessStatus = z.infer<typeof FreshnessStatus>;

/** ISO 8601 UTC + Z 时间（如 2026-08-03T10:00:00Z） */
export const utcDateTime = z.string().datetime();

/**
 * EvidenceRef：证据引用（架构 §3.3）。
 * 注：Python 侧定义在 pipeline/schemas/factlayer.py（经 model_rebuild 解析前向引用）；
 * 前端为避免 risk ↔ factlayer 的运行时循环依赖，统一放在共享原语模块 envelope.ts。
 * 语义与 JSON 输出完全一致。
 */
export const EvidenceRef = z
  .object({
    dataset: z.string().min(1),
    path: z.string().min(1),
    metric: z.string().min(1),
    value: z.union([z.number().finite(), z.string()]),
    updated_at: utcDateTime.nullable(),
  })
  .strict();
export type EvidenceRef = z.infer<typeof EvidenceRef>;

export const BaseEnvelope = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    source: z.union([z.string(), z.array(z.string())]),
    source_updated_at: utcDateTime.nullable(),
    freshness_status: FreshnessStatus,
    data_quality: z.number().finite().min(0).max(1),
    payload: z.record(z.unknown()),
  })
  .strict();
export type BaseEnvelope = z.infer<typeof BaseEnvelope>;

/** 构造带强类型 payload 的数据集信封 schema。 */
export function datasetEnvelope<T extends z.ZodTypeAny>(payloadSchema: T) {
  return z
    .object({
      generated_at: utcDateTime,
      schema_version: z.string().min(1),
      source: z.union([z.string(), z.array(z.string())]),
      source_updated_at: utcDateTime.nullable(),
      freshness_status: FreshnessStatus,
      data_quality: z.number().finite().min(0).max(1),
      payload: payloadSchema,
    })
    .strict();
}
