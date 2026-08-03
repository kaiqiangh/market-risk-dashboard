import type { SupportedLocale } from "@/i18n";

/**
 * 路由路径工具（架构 §1.9：语言段驱动，`#/zh/overview` / `#/en/overview`）。
 * 语言切换不跳首页：仅替换语言段，保留当前页面。
 */

export function localeSegment(locale: SupportedLocale): string {
  return locale === "en" ? "en" : "zh";
}

export function pagePath(locale: SupportedLocale, page: string): string {
  return `/${localeSegment(locale)}/${page}`;
}

/** 从 hash（#/zh/overview）提取页面段。 */
export function pageFromHash(hash: string): string {
  const parts = hash.replace(/^#\/?/, "").split("/");
  return parts[1] ?? "overview";
}
