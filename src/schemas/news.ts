import { z } from "zod";
import { datasetEnvelope, utcDateTime } from "./envelope";

export const NewsSentiment = z.enum(["positive", "negative", "neutral"]);

export const NewsItem = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1),
    title_zh: z.string().nullable(),
    source: z.string().min(1),
    url: z.string().min(1),
    published_at: utcDateTime,
    categories: z.array(z.string()),
    assets: z.array(z.string()),
    importance: z.number().finite().min(0).max(100),
    sentiment: NewsSentiment.nullable(),
    summary: z.string(),
    impact_window: z.string().nullable(),
  })
  .strict();

export const NewsDataset = z
  .object({
    items: z.array(NewsItem),
    total: z.number().int().min(0),
    updated_at: utcDateTime.nullable(),
  })
  .strict();

export const NewsEnvelope = datasetEnvelope(NewsDataset);

export const NewsTranslation = z
  .object({
    id: z.string().min(1),
    title_zh: z.string().min(1),
    summary_zh: z.string().nullable(),
  })
  .strict();

export const NewsTranslationsDataset = z
  .object({
    items: z.array(NewsTranslation),
    updated_at: utcDateTime.nullable(),
  })
  .strict();

export type NewsSentiment = z.infer<typeof NewsSentiment>;
export type NewsItem = z.infer<typeof NewsItem>;
export type NewsDataset = z.infer<typeof NewsDataset>;
export type NewsEnvelope = z.infer<typeof NewsEnvelope>;
export type NewsTranslation = z.infer<typeof NewsTranslation>;
export type NewsTranslationsDataset = z.infer<typeof NewsTranslationsDataset>;
