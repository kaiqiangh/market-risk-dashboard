import { z } from "zod";
import { datasetEnvelope, utcDateTime } from "./envelope";

export const Market = z.enum(["US", "CN", "KR", "HK"]);

export const EquityAsset = z
  .object({
    symbol: z.string().min(1),
    name: z.string().min(1),
    name_zh: z.string().nullable(),
    market: Market,
    sector: z.string(),
    theme: z.array(z.string()),
    price: z.number().finite(),
    currency: z.string(),
    change_1d: z.number().finite().nullable(),
    change_1w: z.number().finite().nullable(),
    change_1m: z.number().finite().nullable(),
    change_ytd: z.number().finite().nullable(),
    volume: z.number().finite().nullable(),
    market_cap: z.number().finite().nullable(),
    ma50_distance_pct: z.number().finite().nullable(),
    ma200_distance_pct: z.number().finite().nullable(),
    rsi14: z.number().finite().min(0).max(100).nullable(),
    percentile_1y: z.number().finite().min(0).max(100).nullable(),
    percentile_1y_obs: z.number().int().min(0),
    source: z.string().min(1),
    updated_at: utcDateTime,
    is_proxy: z.boolean(),
  })
  .strict();

export const EquitiesDataset = z
  .object({
    assets: z.array(EquityAsset),
  })
  .strict();

export const EquitiesEnvelope = datasetEnvelope(EquitiesDataset);

export type Market = z.infer<typeof Market>;
export type EquityAsset = z.infer<typeof EquityAsset>;
export type EquitiesDataset = z.infer<typeof EquitiesDataset>;
export type EquitiesEnvelope = z.infer<typeof EquitiesEnvelope>;
