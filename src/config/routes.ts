import type { SupportedLocale } from "@/i18n";

/**
 * Route path utilities (architecture §1.9: driven by the language segment, `#/zh/overview` / `#/en/overview`).
 * Language switching does not navigate home: it only replaces the language segment and keeps the current page.
 */

export function localeSegment(locale: SupportedLocale): string {
  return locale === "en" ? "en" : "zh";
}

export function pagePath(locale: SupportedLocale, page: string): string {
  return `/${localeSegment(locale)}/${page}`;
}

/** Extract the page segment from the hash (#/zh/overview). */
export function pageFromHash(hash: string): string {
  const parts = hash.replace(/^#\/?/, "").split("/");
  return parts[1] ?? "overview";
}
