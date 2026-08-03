/**
 * 展示层格式化封装（架构 §8.2/§8.3/§1.9）。
 * - 原始数据一律 ISO 8601 UTC + 原始数值；仅本模块负责转本地时区与本地化。
 * - 所有格式化经 Intl.* 按当前语言输出；中英双语词（涨跌/百分位/货币单位）作为
 *   格式化器的固定词汇表，与 UI 文案（i18n key）分离。
 */

export type FormatLocale = "zh-CN" | "en";

/** 转为 Intl 标准 locale（en → en-US，其余 → zh-CN）。 */
export function toIntlLocale(locale: string): string {
  return locale === "en" || locale.startsWith("en") ? "en-US" : "zh-CN";
}

/** 是否为中文 locale。 */
export function isZh(locale: string): boolean {
  return locale === "zh-CN" || locale.startsWith("zh");
}

/** 缺失/非法值统一占位符（不译，通用符号）。 */
export const NA = "—";

function safeDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** 日期：中文 2026年8月3日 / 英文 Aug 3, 2026（架构 T04 format 要求）。 */
export function formatDate(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    year: "numeric",
    month: isZh(locale) ? "long" : "short",
    day: "numeric",
  }).format(d);
}

/** 日期+时间（本地时区）。 */
export function formatDateTime(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

/** 仅时间（本地时区）。 */
export function formatTime(iso: string | null | undefined, locale: string = "zh-CN"): string {
  const d = safeDate(iso);
  if (!d) return NA;
  return new Intl.DateTimeFormat(toIntlLocale(locale), {
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}

/** 通用数字（默认最多 2 位小数）。 */
export function formatNumber(
  value: number | null | undefined,
  locale: string = "zh-CN",
  maximumFractionDigits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NA;
  return new Intl.NumberFormat(toIntlLocale(locale), { maximumFractionDigits }).format(value);
}

/** 带符号数字：+2.35 / -1.20（用于变化量）。 */
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

/** 百分点数值（如 change_1d=2.35 表示 +2.35%）→ "+2.35%" / "-1.20%"。 */
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

/** 0-1 比例（如 confidence=0.72）→ "72.0%"。 */
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
 * 涨跌文案：中文 "上涨 2.35%" / 英文 "Up 2.35%"（架构 T04 format 要求）。
 * value 为百分点（2.35 → +2.35%）；方向由词表达，数值取绝对值（保留 2 位小数）。
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

/** 5Y 百分位：中文 "78.4百分位" / 英文 "78.4th pct"。 */
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

/** 宏观单位 → 展示后缀（pct 追加 %，usd 用 USD 缩写等；词表为格式化器词汇）。 */
export function formatUnitSuffix(unit: string, locale: string = "zh-CN"): string {
  const base = UNIT_SUFFIX_WORDS[unit] ?? "";
  if (unit === "usd") return base;
  if (unit === "bps") return isZh(locale) ? "bp" : base;
  return base;
}

/** 紧凑数字：中文 12.3亿 / 英文 1.23B（不追加货币）。 */
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
 * 货币：中文 "3.2万亿美元" / 英文 "$3.2T"（架构 T04 format 要求）。
 * 中文用紧凑记数 + 货币词；英文用 Intl 货币紧凑格式（自动 $/T 后缀）。
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

/** 货币全量：$1,234.56 / ¥8,900。 */
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

/** 相对时间：Intl.RelativeTimeFormat（中文 "3 天前" / 英文 "3 days ago"）。 */
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
