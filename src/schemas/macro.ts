import { z } from "zod";
import { datasetEnvelope, FreshnessStatus, utcDateTime } from "./envelope";

export const MacroUnit = z.enum(["pct", "bps", "index", "usd", "ratio", "level"]);

export const MacroIndicator = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    value: z.number().finite().nullable(),
    previous: z.number().finite().nullable(),
    change_1m: z.number().finite().nullable(),
    unit: MacroUnit,
    source: z.string().min(1),
    updated_at: utcDateTime.nullable(),
    status: FreshnessStatus,
  })
  .strict();

export const FedWatchRateProb = z
  .object({
    target_rate: z.number().finite(),
    probability: z.number().finite().min(0).max(1),
    change_1d: z.number().finite().nullable(),
  })
  .strict();

export const FedWatchSnapshot = z
  .object({
    meeting_date: utcDateTime.nullable(),
    effective_rate: z.number().finite(),
    implied_rate: z.number().finite(),
    probabilities: z.array(FedWatchRateProb),
    inferred_action: z.enum(["hold", "hike", "cut", "insufficient_data"]).nullable(),
    change_1d: z.record(z.number().finite()).nullable(),
    status: z.enum(["accumulating", "ready"]),
  })
  .strict();

export const MacroDataset = z
  .object({
    rates: z.array(MacroIndicator).default([]),
    credit: z.array(MacroIndicator).default([]),
    inflation: z.array(MacroIndicator).default([]),
    labor: z.array(MacroIndicator).default([]),
    liquidity: z.array(MacroIndicator).default([]),
    fx: z.array(MacroIndicator).default([]),
    fedwatch: FedWatchSnapshot.nullable(),
  })
  .strict();

export const MacroEnvelope = datasetEnvelope(MacroDataset);

export type MacroUnit = z.infer<typeof MacroUnit>;
export type MacroIndicator = z.infer<typeof MacroIndicator>;
export type FedWatchRateProb = z.infer<typeof FedWatchRateProb>;
export type FedWatchSnapshot = z.infer<typeof FedWatchSnapshot>;
export type MacroDataset = z.infer<typeof MacroDataset>;
export type MacroEnvelope = z.infer<typeof MacroEnvelope>;
