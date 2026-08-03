import { z } from "zod";
import { MarketRegime, RiskLevel } from "./risk";

/**
 * History slice contract (architecture §1.7 / §3.6).
 * The pipeline produces history/{series}/{slice}.json as **plain arrays** (not envelopes),
 * with very narrow rows: date + score + per-dimension scores (risk) / date + symbol + close (market).
 * The frontend explicitly passes this schema via DatasetClient.fetch(key, { slice }, historySchema).
 */

/** Risk history slice row (history/risk/30d.json etc.). */
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

/** Market history slice row (history/market/30d.json etc.). */
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
