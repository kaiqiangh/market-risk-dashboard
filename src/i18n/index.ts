import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonZhCN from "./locales/zh-CN/common.json";
import commonEn from "./locales/en/common.json";

/**
 * i18n 初始化（架构 §1.9）。
 * 语言优先级：URL 语言段 → localStorage `market_dashboard_locale` → 浏览器语言 → 默认 zh-CN。
 * 命名空间：common/dashboard/macro/equities/sectors/news/calendar/risk/status（T04 逐页补齐）。
 */

export const SUPPORTED_LOCALES = ["zh-CN", "en"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const LOCALE_STORAGE_KEY = "market_dashboard_locale";

const LOCALE_SEGMENT_MAP: Record<string, SupportedLocale> = {
  zh: "zh-CN",
  zhCN: "zh-CN",
  "zh-CN": "zh-CN",
  en: "en",
};

/** 从 URL hash（#/zh/overview）解析语言段。 */
export function localeFromHash(hash: string): SupportedLocale | null {
  const segment = hash.replace(/^#\/?/, "").split("/")[0] ?? "";
  return LOCALE_SEGMENT_MAP[segment] ?? null;
}

/** 按优先级探测初始语言。 */
export function detectInitialLocale(): SupportedLocale {
  const fromHash = localeFromHash(window.location.hash);
  if (fromHash) return fromHash;

  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  if (stored && (SUPPORTED_LOCALES as readonly string[]).includes(stored)) {
    return stored as SupportedLocale;
  }

  const browserLang = window.navigator.language?.toLowerCase() ?? "";
  if (browserLang.startsWith("zh")) return "zh-CN";
  return "en";
}

void i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { common: commonZhCN },
    en: { common: commonEn },
  },
  lng: detectInitialLocale(),
  fallbackLng: "zh-CN",
  supportedLngs: SUPPORTED_LOCALES as unknown as string[],
  defaultNS: "common",
  ns: ["common"],
  interpolation: {
    escapeValue: false, // React 已做 XSS 转义
  },
  returnNull: false,
});

export default i18n;
