import { z } from "zod";
import { EvidenceRef, FreshnessStatus, utcDateTime } from "./envelope";

/**
 * AI analysis output contract (architecture §3.4).
 * analysis.zh-CN.json / analysis.en.json are self-describing contract files, parsed directly as AnalysisDataset.
 */
export const AnalysisLanguage = z.enum(["zh-CN", "en"]);

export const SignalClaim = z
  .object({
    claim: z.string().min(1),
    evidence_refs: z.array(EvidenceRef),
  })
  .strict();

export const CaseStatement = z
  .object({
    title: z.string().min(1),
    points: z.array(z.string()),
    evidence_refs: z.array(EvidenceRef),
  })
  .strict();

export const AnalysisDataset = z
  .object({
    schema_version: z.string().min(1),
    generated_at: utcDateTime,
    language: AnalysisLanguage,
    market_state: z.string().min(1),
    market_regime: z.string().min(1),
    summary: z.string().min(1),
    top_risk_drivers: z.array(SignalClaim),
    supporting_signals: z.array(SignalClaim),
    contradicting_signals: z.array(SignalClaim),
    what_changed_today: z.array(z.string()),
    watch_next: z.array(z.string()),
    bull_case: CaseStatement,
    base_case: CaseStatement,
    bear_case: CaseStatement,
    confidence: z.number().finite().min(0).max(1),
    evidence_refs: z.array(EvidenceRef),
    data_freshness: FreshnessStatus,
  })
  .strict();

export type AnalysisLanguage = z.infer<typeof AnalysisLanguage>;
export type SignalClaim = z.infer<typeof SignalClaim>;
export type CaseStatement = z.infer<typeof CaseStatement>;
export type AnalysisDataset = z.infer<typeof AnalysisDataset>;
