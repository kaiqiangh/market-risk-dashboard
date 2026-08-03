import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  LOCALE_STORAGE_KEY,
  SUPPORTED_LOCALES,
  localeFromHash,
  type SupportedLocale,
} from "@/i18n";
import { localeSegment, pageFromHash, pagePath } from "@/config/routes";

/**
 * useLocale: language detection + switching (architecture §1.9).
 * - Language priority: URL language segment → localStorage → default en.
 * - Switching: write localStorage + i18n.changeLanguage + replace the URL language segment (keep the current page).
 */
export interface UseLocaleResult {
  locale: SupportedLocale;
  /** Switch to the target language (keep the current page). */
  setLocale: (next: SupportedLocale) => void;
  /** Toggle to the other language. */
  toggleLocale: () => void;
}

export function useLocale(): UseLocaleResult {
  const { i18n } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ lang?: string; page?: string }>();

  const locale: SupportedLocale = SUPPORTED_LOCALES.includes(i18n.language as SupportedLocale)
    ? (i18n.language as SupportedLocale)
    : "en";

  /** Read the current language (read latest at call time to avoid stale closures). */
  const currentLocale = (): SupportedLocale =>
    SUPPORTED_LOCALES.includes(i18n.language as SupportedLocale)
      ? (i18n.language as SupportedLocale)
      : "en";

  const setLocale = (next: SupportedLocale): void => {
    if (next === currentLocale()) return;
    window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    // Language switching does not navigate home: read the current page from the hash (layout components like Navbar cannot access child route params.page)
    const page = params.page ?? pageFromHash(window.location.hash) ?? "overview";
    void i18n.changeLanguage(next);
    navigate(pagePath(next, page), { replace: true });
  };

  const toggleLocale = (): void => {
    setLocale(currentLocale() === "en" ? "zh-CN" : "en");
  };

  return { locale, setLocale, toggleLocale };
}

/**
 * LocaleSync: syncs the URL language segment to i18n (architecture §1.9 priority).
 * Covers direct URL edits / browser back-forward; ensures i18n.language stays consistent when the route language segment changes.
 * Also triggers one local state update so mounted layout subtrees (Navbar etc.) re-render with the language
 * (react-i18next subscription notifications for changeLanguage inside useEffect are unreliable in some environments).
 */
export function LocaleSync(): null {
  const { i18n } = useTranslation();
  const { lang } = useParams<{ lang?: string }>();
  const [, setTick] = useState(0);

  useEffect(() => {
    const target = localeFromHash(window.location.hash);
    if (target && i18n.language !== target) {
      void i18n.changeLanguage(target);
    } else if (!target) {
      const resolved: SupportedLocale = lang === "zh" ? "zh-CN" : "en";
      if (i18n.language !== resolved) void i18n.changeLanguage(resolved);
    }
    setTick((n) => n + 1);
  }, [lang, i18n]);

  return null;
}

/** Convenience: current language segment (zh/en). */
export function useLocaleSegment(): string {
  const { locale } = useLocale();
  return localeSegment(locale);
}
