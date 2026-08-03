import { z } from "zod";
import { FreshnessStatus, utcDateTime } from "./envelope";
import { RiskModelResult } from "./risk";

/**
 * Fact layer contract (architecture §3.3, AI input, language-neutral deterministic facts).
 * facts.json is a self-describing contract file, parsed directly as FactLayer (not wrapped in BaseEnvelope).
 */
export const FactLayer = z
  .object({
    generated_at: utcDateTime,
    schema_version: z.string().min(1),
    data_freshness: z.record(FreshnessStatus),
    risk: RiskModelResult,
    macro_summary: z.record(z.unknown()),
    market_summary: z.record(z.unknown()),
    news_top: z.array(z.record(z.unknown())),
    calendar_next7d: z.array(z.record(z.unknown())),
    evidence_index: z.record(z.unknown()),
  })
  .strict();

export type FactLayer = z.infer<typeof FactLayer>;
