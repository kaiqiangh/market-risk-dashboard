/**
 * Display-layer formatting wrapper (architecture §8.2/§8.3/§1.9).
 * - Raw data is always ISO 8601 UTC + raw values; only this module converts to local timezone and localizes.
 * - All formatting outputs via Intl.* in the current language; bilingual words (up/down, percentile, currency units) act as
 *   the formatter's fixed vocabulary, separated from UI copy (i18n keys).
 */

export type FormatLocale = "zh-CN" | "en";

/** Convert to an Intl standard locale (en → en-US, others → zh-CN). */
export function toIntlLocale(locale: string): string {
  return locale === "en" || locale.startsWith("en") ? "en-US" : "zh-CN";
}

/** Whether the locale is Chinese. */
export function isZh(locale: string): boolean {
  return locale === "zh-CN" || locale.startsWith("zh");
}

/** Unified placeholder for missing/invalid values (not translated, universal symbol). */
export const NA = "—";

function safeDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** Date: localized per locale (zh-CN long month form / en short month form), architecture T04 format requirement. */
export function formatDate(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    year: "numeric",
    month: isZh(locale) ? "long" : "short",
    day: "numeric",
  }).format(d);
}

/** Date + time (local timezone). */
export function formatDateTime(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

/** Time only (local timezone). */
export function formatTime(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/** Generic number (at most 2 decimal places by default). */
export function formatNumber(
  value: number | null | undefined,
  locale: string = "zh-CN",
  maximumFractionDigits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), { maximumFractionDigits }).format(value);
}

/** Signed number: +2.35 / -1.20 (for change values). */
export function formatSignedNumber(
  value: number | null | undefined,
  locale: string = "zh-CN",
  maximumFractionDigits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), {
    signDisplay: "exceptZero",
    maximumFractionDigits,
  }).format(value);
}

/** Percentage points (e.g. change_1d=2.35 means +2.35%) → "+2.35%" / "-1.20%". */
export function formatPctPoints(
  value: number | null | undefined,
  locale: string = "zh-CN",
  maximumFractionDigits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return `${new Intl.NumberFormat(toIntlLocale(locale), {
    signDisplay: "exceptZero",
    minimumFractionDigits: maximumFractionDigits,
    maximumFractionDigits,
  }).format(value)}%`;
}

/** 0-1 ratio (e.g. confidence=0.72) → "72.0%". */
export function formatRatio(
  value: number | null | undefined,
  locale: string = "zh-CN",
  maximumFractionDigits = 1,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), {
    style: "percent",
    maximumFractionDigits,
  }).format(value);
}

const CHANGE_UP_WORDS: Record<string, string> = { "zh-CN": "上涨", en: "Up" };
const CHANGE_DOWN_WORDS: Record<string, string> = { "zh-CN": "下跌", en: "Down" };

/**
 * Change label: zh-CN uses the localized up/down words, en uses "Up"/"Down" + value (architecture T04 format requirement).
 * value is in percentage points (2.35 → +2.35%); direction is expressed by the word, and the value uses its absolute value (2 decimal places).
 */
export function formatChange(value: number | null | undefined, locale: string = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  const key = isZh(locale) ? "zh-CN" : "en";
  const word = value > 0 ? CHANGE_UP_WORDS[key] : value < 0 ? CHANGE_DOWN_WORDS[key] : "";
  const num = new Intl.NumberFormat(toIntlLocale(locale), {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  return word ? `${word} ${num}%` : `${num}%`;
}

/** 5Y percentile: zh-CN appends the localized pct suffix / en "78.4th pct". */
export function formatPercentile(value: number | null | undefined, locale: string = "zh-CN"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  const num = new Intl.NumberFormat(toIntlLocale(locale), { maximumFractionDigits: 1 }).format(value);
  return isZh(locale) ? `${num}百分位` : `${num}th pct`;
}

const UNIT_SUFFIX_WORDS: Record<string, string> = {
  pct: "%",
  bps: "bps",
  index: "",
  usd: "USD",
  ratio: "",
  level: "",
};

/** Macro unit → display suffix (pct appends %, usd uses the USD abbreviation, etc.; the vocabulary belongs to the formatter). */
export function formatUnitSuffix(unit: string, locale: string = "zh-CN"): string {
  const base = UNIT_SUFFIX_WORDS[unit] ?? "";
  if (unit === "usd") return base;
  if (unit === "bps") return isZh(locale) ? "bp" : base;
  return base;
}

/** Compact number: zh-CN compact form / en "1.23B" (no currency appended). */
export function formatCompactNumber(
  value: number | null | undefined,
  locale: string = "zh-CN",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

const CURRENCY_WORDS: Record<string, string> = { USD: "美元", CNY: "人民币", HKD: "港元", KRW: "韩元" };

/**
 * Money: zh-CN compact notation + currency word / en "$3.2T" (architecture T04 format requirement).
 * Chinese uses compact notation + currency word; English uses Intl compact currency format (auto $/T suffix).
 */
export function formatMoneyCompact(
  value: number | null | undefined,
  currency: string = "USD",
  locale: string = "zh-CN",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  if (isZh(locale)) {
    const num = new Intl.NumberFormat("zh-CN", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
    const word = CURRENCY_WORDS[currency] ?? currency;
    return `${num}${word}`;
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Full money: $1,234.56 / ¥8,900. */
export function formatMoney(
  value: number | null | undefined,
  currency: string = "USD",
  locale: string = "zh-CN",
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

/** Relative time: Intl.RelativeTimeFormat (localized per locale). */
export function formatRelativeTime(
  iso: string | null | undefined,
  locale: string = "zh-CN",
  now: number = Date.now(),
): string {
  const d = safeDate(iso);
  if (!d) return NA;
  const rtf = new Intl.RelativeTimeFormat(toIntlLocale(locale), { numeric: "auto" });
  const diffMs = d.getTime() - now;
  const diffMin = Math.round(diffMs / 60_000);
  const absMin = Math.abs(diffMin);
  if (absMin < 1) return rtf.format(0, "minute");
  if (absMin < 60) return rtf.format(diffMin, "minute");
  const diffHour = Math.round(diffMs / 3_600_000);
  if (Math.abs(diffHour) < 24) return rtf.format(diffHour, "hour");
  const diffDay = Math.round(diffMs / 86_400_000);
  if (Math.abs(diffDay) < 30) return rtf.format(diffDay, "day");
  const diffMonth = Math.round(diffMs / 2_592_000_000);
  return rtf.format(diffMonth, "month");
}
