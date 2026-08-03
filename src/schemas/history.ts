import { z } from "zod";
import { MarketRegime, RiskLevel } from "./risk";

/**
 * 历史切片契约（架构 §1.7 / §3.6）。
 * 管道产出 history/{series}/{slice}.json 为**纯数组**（非 envelope），
 * 行级极窄：日期 + 分数 + 各维分数（风险）/ 日期 + 代码 + 收盘（行情）。
 * 前端通过 DatasetClient.fetch(key, { slice }, historySchema) 显式传入本 schema 解析。
 */

/** 风险历史切片行（history/risk/30d.json 等）。 */
export const RiskTrendPoint = z
  .object({
    date: z.string().min(1), // YYYY-MM-DD
    total_score: z.number().finite().min(0).max(100),
    risk_level: RiskLevel.optional(),
    regime: MarketRegime.optional(),
    confidence: z.number().finite().min(0).max(1).optional(),
    dim_scores: z.record(z.number().finite()).optional(),
  })
  .strict();

export const RiskTrendSlice = z.array(RiskTrendPoint);

/** 行情历史切片行（history/market/30d.json 等）。 */
export const MarketSlicePoint = z
  .object({
    date: z.string().min(1), // YYYY-MM-DD
    symbol: z.string().min(1),
    close: z.number().finite(),
  })
  .strict();

export const MarketSlice = z.array(MarketSlicePoint);

export type RiskTrendPoint = z.infer<typeof RiskTrendPoint>;
export type RiskTrendSlice = z.infer<typeof RiskTrendSlice>;
export type MarketSlicePoint = z.infer<typeof MarketSlicePoint>;
export type MarketSlice = z.infer<typeof MarketSlice>;
