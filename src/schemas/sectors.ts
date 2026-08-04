import { z } from "zod";
import { datasetEnvelope, utcDateTime } from "./envelope";

export const SectorItem = z
  .object({
    key: z.string().min(1),
    label: z.string().min(1),
    label_zh: z.string().nullable(),
    change_1d: z.number().finite().nullable(),
    change_1w: z.number().finite().nullable(),
    change_1m: z.number().finite().nullable(),
    percentile_1y: z.number().finite().min(0).max(100).nullable(),
    percentile_1y_obs: z.number().int().min(0),
    updated_at: utcDateTime.nullable(),
  })
  .strict();

export const MemoryProxy = z
  .object({
    label: z.string().min(1),
    label_zh: z.string().nullable(),
    change_1w: z.number().finite().nullable(),
    change_1m: z.number().finite().nullable(),
    note: z.string().nullable(),
    updated_at: utcDateTime.nullable(),
  })
  .strict();

export const SectorsDataset = z
  .object({
    sectors: z.array(SectorItem),
    themes: z.array(SectorItem),
    memory: MemoryProxy.nullable(),
  })
  .strict();

export const SectorsEnvelope = datasetEnvelope(SectorsDataset);

export type SectorItem = z.infer<typeof SectorItem>;
export type MemoryProxy = z.infer<typeof MemoryProxy>;
export type SectorsDataset = z.infer<typeof SectorsDataset>;
export type SectorsEnvelope = z.infer<typeof SectorsEnvelope>;
