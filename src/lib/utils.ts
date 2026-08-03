import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * 工具函数（T02 骨架：shadcn cn + 基础格式化占位；完整 Intl 格式化封装在 T04 src/lib/format.ts）。
 */

/** shadcn/ui 类名合并。 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** 数字格式化（展示层用，原始数据一律不格式化存储，架构 §8.3）。 */
export function formatNumber(value: number | null | undefined, locale = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

/** 百分比格式化（0-1 输入 → "12.3%"）。 */
export function formatPercent(value: number | null | undefined, locale = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

/** ISO 8601 UTC → 本地时间展示（架构 §8.2：仅展示层转本地）。 */
export function formatDateTime(iso: string | null | undefined, locale = "zh-CN"): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
