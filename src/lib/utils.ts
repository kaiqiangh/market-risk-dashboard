import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Utility functions (T02 skeleton: shadcn cn + basic formatting placeholders; the full Intl formatting wrapper lands in T04 src/lib/format.ts).
 */

/** shadcn/ui class name merger. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Number formatting (display layer only; raw data is never stored formatted, architecture §8.3). */
export function formatNumber(value: number | null | undefined, locale = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

/** Percent formatting (0-1 input → "12.3%"). */
export function formatPercent(value: number | null | undefined, locale = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

/** ISO 8601 UTC → local time display (architecture §8.2: only the display layer converts to local). */
export function formatDateTime(iso: string | null | undefined, locale = "zh-CN"): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
