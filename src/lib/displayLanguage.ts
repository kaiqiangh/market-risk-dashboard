import i18n, { type SupportedLocale } from "@/i18n";
import machineTokens from "./machineTokens.json";

export type DisplayLocale = SupportedLocale | string;

const MACHINE_TOKEN_PATTERN = new RegExp(`\\b(?:${machineTokens.join("|")})\\b`, "gi");
const URL_PATTERN = /https?:\/\/\S+/gi;
const CJK_PATTERN = /[\u3400-\u9fff]/u;
const LATIN_PATTERN = /[A-Za-z]/u;
const TEMPLATE_PATTERN = /\{\{[^}]+\}\}/g;

const PROVIDER_LABEL_KEYS: Record<string, string> = {
  akshare: "akshare",
  calibration_panel: "calibrationPanel",
  coingecko: "coingecko",
  computed: "computed",
  fmp: "fmp",
  fmp_quotes: "fmpQuotes",
  fred: "fred",
  fred_calendar: "fredCalendar",
  risk_model: "riskModel",
  rss_news: "rssNews",
  yfinance: "yfinance",
  yfinance_a_share: "yfinanceAShare",
};

const NEWS_SOURCE_LABEL_KEYS: Record<string, string> = {
  cnbc: "cnbc",
  "cnbc news": "cnbc",
  clschina: "market",
  "\u8d22\u8054\u793e": "market",
  eastmoney: "market",
  fed: "federalReserve",
  "federal reserve": "federalReserve",
  investing: "market",
  "investing.com": "market",
  marketwatch: "market",
  "marketwatch news": "market",
  wallstreetcn: "market",
  "\u534e\u5c14\u8857\u89c1\u95fb": "market",
};

const CRYPTO_NAME_KEYS: Record<string, string> = {
  BTC: "bitcoin",
  ETH: "ethereum",
  SOL: "solana",
};

function isChinese(locale: DisplayLocale): boolean {
  return locale.toLowerCase().startsWith("zh");
}

function translate(locale: DisplayLocale, namespace: string, key: string): string {
  return i18n.t(key, { lng: locale, ns: namespace, defaultValue: key });
}

export function localizedFallback(locale: DisplayLocale, kind: "asset" | "event" | "provider" | "source" | "translation" = "translation"): string {
  return translate(locale, "common", `display.fallback.${kind}`);
}

export function displayProvider(provider: string | null | undefined, locale: DisplayLocale): string {
  const key = provider?.trim().toLowerCase();
  return key && PROVIDER_LABEL_KEYS[key]
    ? translate(locale, "common", `display.providerNames.${PROVIDER_LABEL_KEYS[key]}`)
    : localizedFallback(locale, "provider");
}

export function displayNewsSource(source: string | null | undefined, locale: DisplayLocale): string {
  const normalized = source?.trim();
  const key = normalized?.toLowerCase();
  return key && NEWS_SOURCE_LABEL_KEYS[key]
    ? translate(locale, "common", `display.newsSourceNames.${NEWS_SOURCE_LABEL_KEYS[key]}`)
    : localizedFallback(locale, "source");
}

export function displayReasonDetail(detail: string | null | undefined, locale: DisplayLocale): string {
  const normalized = detail?.trim().toLowerCase() ?? "";
  const key = normalized.includes("429") || normalized.includes("rate limited")
    ? "rateLimited"
    : normalized.includes("403") || normalized.includes("forbidden")
      ? "accessDenied"
      : normalized.includes("no events")
        ? "noEvents"
        : normalized.includes("remotedisconnected") || normalized.includes("disconnected")
          ? "connectionInterrupted"
          : normalized
            ? "generic"
            : "unknown";
  return translate(locale, "common", `display.reasonDetails.${key}`);
}

export function displayLocalizedValue(
  value: string | null | undefined,
  valueZh: string | null | undefined,
  locale: DisplayLocale,
  kind: "asset" | "translation" = "asset",
): string {
  if (isChinese(locale)) {
    return valueZh?.trim() && isDisplayTextSafe(valueZh, locale)
      ? valueZh.trim()
      : localizedFallback(locale, kind);
  }
  return value?.trim() && !CJK_PATTERN.test(value) ? value : localizedFallback(locale, kind);
}

export function displayCryptoName(symbol: string, name: string | null | undefined, locale: DisplayLocale): string {
  const key = CRYPTO_NAME_KEYS[symbol.toUpperCase()];
  return key ? translate(locale, "common", `display.cryptoNames.${key}`) : displayLocalizedValue(name, null, locale);
}

export function displayEventTitle(title: string, locale: DisplayLocale): string {
  if (!title.trim()) return localizedFallback(locale, "event");
  if (!isChinese(locale)) return CJK_PATTERN.test(title) ? localizedFallback(locale, "event") : title;

  const earnings = title.match(/^([A-Z][A-Z0-9.:-]*)\s+Earnings$/i);
  if (earnings) return `${earnings[1]} ${translate(locale, "calendar", "display.earningsSuffix")}`;
  const known: Record<string, string> = {
    "Consumer Price Index": "consumerPriceIndex",
    "Producer Price Index": "producerPriceIndex",
    "Advance Retail Sales": "advanceRetailSales",
  };
  return known[title]
    ? translate(locale, "calendar", `display.events.${known[title]}`)
    : (CJK_PATTERN.test(title) ? title : localizedFallback(locale, "event"));
}

/**
 * Human-readable generated text must stay in the active locale. Machine tokens,
 * numbers, dates and URLs are allowed because they are identifiers or evidence.
 */
export function isDisplayTextSafe(text: string | null | undefined, locale: DisplayLocale): boolean {
  if (!text?.trim()) return false;
  const withoutMachineText = text
    .replace(URL_PATTERN, " ")
    .replace(TEMPLATE_PATTERN, " ")
    .replace(MACHINE_TOKEN_PATTERN, " ");
  return isChinese(locale) ? !LATIN_PATTERN.test(withoutMachineText) : !CJK_PATTERN.test(withoutMachineText);
}

export function safeDisplayText(
  text: string | null | undefined,
  locale: DisplayLocale,
  fallback = localizedFallback(locale, "translation"),
): string {
  return isDisplayTextSafe(text, locale) ? text!.trim() : fallback;
}
