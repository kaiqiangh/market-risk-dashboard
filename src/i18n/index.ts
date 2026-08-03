import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import commonZhCN from "./locales/zh-CN/common.json";
import dashboardZhCN from "./locales/zh-CN/dashboard.json";
import macroZhCN from "./locales/zh-CN/macro.json";
import equitiesZhCN from "./locales/zh-CN/equities.json";
import themesZhCN from "./locales/zh-CN/themes.json";
import newsZhCN from "./locales/zh-CN/news.json";
import calendarZhCN from "./locales/zh-CN/calendar.json";
import riskZhCN from "./locales/zh-CN/risk.json";
import statusZhCN from "./locales/zh-CN/status.json";
import commonEn from "./locales/en/common.json";
import dashboardEn from "./locales/en/dashboard.json";
import macroEn from "./locales/en/macro.json";
import equitiesEn from "./locales/en/equities.json";
import themesEn from "./locales/en/themes.json";
import newsEn from "./locales/en/news.json";
import calendarEn from "./locales/en/calendar.json";
import riskEn from "./locales/en/risk.json";
import statusEn from "./locales/en/status.json";

/**
 * i18n initialization (architecture §1.9).
 * Language priority: URL language segment → localStorage `market_dashboard_locale` → browser language → default zh-CN.
 * Namespaces (PRD §8.5): common/dashboard/macro/equities/sectors/news/calendar/risk/status.
 * Note: PRD originally included the sectors namespace; the frontend carries sector/theme copy in the themes namespace;
 *       sectors data (sectors/themes) itself comes from data files (label/label_zh) and does not occupy a translation namespace.
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

/** Parse the language segment from the URL hash (#/zh/overview). */
export function localeFromHash(hash: string): SupportedLocale | null {
  const segment = hash.replace(/^#\/?/, "").split("/")[0] ?? "";
  return LOCALE_SEGMENT_MAP[segment] ?? null;
}

/** Detect the initial language by priority. */
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

export const NAMESPACES = [
  "common",
  "dashboard",
  "macro",
  "equities",
  "themes",
  "news",
  "calendar",
  "risk",
  "status",
] as const;

void i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": {
      common: commonZhCN,
      dashboard: dashboardZhCN,
      macro: macroZhCN,
      equities: equitiesZhCN,
      themes: themesZhCN,
      news: newsZhCN,
      calendar: calendarZhCN,
      risk: riskZhCN,
      status: statusZhCN,
    },
    en: {
      common: commonEn,
      dashboard: dashboardEn,
      macro: macroEn,
      equities: equitiesEn,
      themes: themesEn,
      news: newsEn,
      calendar: calendarEn,
      risk: riskEn,
      status: statusEn,
    },
  },
  lng: detectInitialLocale(),
  fallbackLng: "zh-CN",
  supportedLngs: SUPPORTED_LOCALES as unknown as string[],
  defaultNS: "common",
  ns: [...NAMESPACES],
  interpolation: {
    escapeValue: false, // React already performs XSS escaping
  },
  returnNull: false,
});

export default i18n;
