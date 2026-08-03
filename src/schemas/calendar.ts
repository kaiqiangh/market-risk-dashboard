import { z } from "zod";
import { datasetEnvelope, utcDateTime } from "./envelope";

export const EventType = z.enum(["economic", "earnings"]);
export const EventImportance = z.enum(["high", "medium", "low"]);

export const CalendarEvent = z
  .object({
    id: z.string().min(1),
    type: EventType,
    title: z.string().min(1),
    country: z.string().nullable(),
    datetime: utcDateTime,
    importance: EventImportance,
    actual: z.number().finite().nullable(),
    forecast: z.number().finite().nullable(),
    previous: z.number().finite().nullable(),
    unit: z.string().nullable(),
    related_assets: z.array(z.string()),
    source: z.string().min(1),
  })
  .strict();

export const CalendarDataset = z
  .object({
    events: z.array(CalendarEvent),
    updated_at: utcDateTime.nullable(),
  })
  .strict();

export const CalendarEnvelope = datasetEnvelope(CalendarDataset);

export type EventType = z.infer<typeof EventType>;
export type EventImportance = z.infer<typeof EventImportance>;
export type CalendarEvent = z.infer<typeof CalendarEvent>;
export type CalendarDataset = z.infer<typeof CalendarDataset>;
export type CalendarEnvelope = z.infer<typeof CalendarEnvelope>;
