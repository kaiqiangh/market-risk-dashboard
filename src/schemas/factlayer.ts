import { z } from "zod";
import { FreshnessStatus, utcDateTime } from "./envelope";
import { RiskModelResult } from "./risk";

/**
 * 事实层契约（架构 §3.3，AI 输入，语言无关确定性事实）。
 * facts.json 为自描述契约文件，直接以 FactLayer 解析（不包裹 BaseEnvelope）。
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
