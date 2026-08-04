import { z } from "zod";

/**
 * Global data Envelope (architecture §3.1, isomorphic with pipeline/schemas/envelope.py).
 * - strict(): disallow implicit fields (additionalProperties=false isomorphic)
 * - finite(): reject NaN/Infinity
 * - datetime(): ISO 8601 UTC + Z
 */

export const FreshnessStatus = z.enum(["fresh", "delayed", "stale", "missing", "degraded"]);
export type FreshnessStatus = z.infer<typeof FreshnessStatus>;

/** ISO 8601 UTC + Z timestamp (e.g. 2026-08-03T10:00:00Z) */
export const utcDateTime = z.string().datetime();

/**
 * ProviderProvenance: which provider actually served the dataset (#65, ADR 0004).
 * Isomorphic with pipeline/schemas/envelope.py::ProviderProvenance.
 */
export const ProviderProvenance = z
  .object({
    provider: z.string().min(1),
    used_fallback: z.boolean(),
    from_cache: z.boolean(),
  })
  .strict();
export type ProviderProvenance = z.infer<typeof ProviderProvenance>;

/** The shared envelope field set (isomorphic with BaseEnvelope in pipeline/schemas/envelope.py). */
const ENVELOPE_FIELDS = {
  generated_at: utcDateTime,
  schema_version: z.string().min(1),
  source: z.union([z.string(), z.array(z.string())]),
  source_updated_at: utcDateTime.nullable(),
  freshness_status: FreshnessStatus,
  data_quality: z.number().finite().min(0).max(1),
  provenance: ProviderProvenance,
};

/**
 * EvidenceRef: evidence reference (architecture §3.3).
 * Note: the Python side defines it in pipeline/schemas/factlayer.py (forward reference resolved via model_rebuild);
 * the frontend keeps it in the shared primitive module envelope.ts to avoid a runtime circular dependency between risk ↔ factlayer.
 * Semantics are identical to the JSON output.
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
    ...ENVELOPE_FIELDS,
    payload: z.record(z.unknown()),
  })
  .strict();
export type BaseEnvelope = z.infer<typeof BaseEnvelope>;

/** Build a dataset envelope schema with a strongly typed payload. */
export function datasetEnvelope<T extends z.ZodTypeAny>(payloadSchema: T) {
  return z
    .object({
      ...ENVELOPE_FIELDS,
      payload: payloadSchema,
    })
    .strict();
}
