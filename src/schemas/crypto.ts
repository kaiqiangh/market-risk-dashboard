import { z } from "zod";
import { datasetEnvelope, utcDateTime } from "./envelope";

export const CryptoSentiment = z.enum(["risk_on", "risk_off", "neutral"]);

export const CryptoAsset = z
  .object({
    symbol: z.string().min(1),
    name: z.string().min(1),
    price: z.number().finite(),
    change_1d: z.number().finite().nullable(),
    change_1w: z.number().finite().nullable(),
    change_1m: z.number().finite().nullable(),
    market_cap: z.number().finite().nullable(),
    volume_24h: z.number().finite().nullable(),
    source: z.string().min(1),
    updated_at: utcDateTime,
  })
  .strict();

export const CryptoDataset = z
  .object({
    assets: z.array(CryptoAsset),
    btc_dominance: z.number().finite().min(0).max(1).nullable(),
    stablecoin_mcap: z.number().finite().nullable(),
    market_cap_total: z.number().finite().nullable(),
    sentiment: CryptoSentiment.nullable(),
  })
  .strict();

export const CryptoEnvelope = datasetEnvelope(CryptoDataset);

export type CryptoSentiment = z.infer<typeof CryptoSentiment>;
export type CryptoAsset = z.infer<typeof CryptoAsset>;
export type CryptoDataset = z.infer<typeof CryptoDataset>;
export type CryptoEnvelope = z.infer<typeof CryptoEnvelope>;
