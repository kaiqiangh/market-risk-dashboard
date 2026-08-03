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
 * useLocale：语言探测 + 切换（架构 §1.9）。
 * - 语言优先级：URL 语言段 → localStorage → 浏览器 → 默认 zh-CN。
 * - 切换：写 localStorage + i18n.changeLanguage + 替换 URL 语言段（保持当前页面）。
 */
export interface UseLocaleResult {
  locale: SupportedLocale;
  /** 切换到目标语言（保持当前页面）。 */
  setLocale: (next: SupportedLocale) => void;
  /** 切换为另一种语言。 */
  toggleLocale: () => void;
}

export function useLocale(): UseLocaleResult {
  const { i18n } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ lang?: string; page?: string }>();

  const locale: SupportedLocale = SUPPORTED_LOCALES.includes(i18n.language as SupportedLocale)
    ? (i18n.language as SupportedLocale)
    : "zh-CN";

  /** 读取当前语言（调用时取最新，避免闭包过期）。 */
  const currentLocale = (): SupportedLocale =>
    SUPPORTED_LOCALES.includes(i18n.language as SupportedLocale)
      ? (i18n.language as SupportedLocale)
      : "zh-CN";

  const setLocale = (next: SupportedLocale): void => {
    if (next === currentLocale()) return;
    window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    // 语言切换不跳首页：从 hash 取当前页面（Navbar 等布局组件拿不到子路由 params.page）
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
 * LocaleSync：把 URL 语言段同步到 i18n（架构 §1.9 优先级）。
 * 覆盖直接改 URL / 浏览器前进后退的场景；路由语言段变化时保证 i18n.language 一致。
 * 额外触发一次本地 state 更新，确保已挂载的布局子树（Navbar 等）随语言重渲染
 * （react-i18next 对 useEffect 内 changeLanguage 的订阅通知在部分环境不可靠）。
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
      const resolved: SupportedLocale = lang === "en" ? "en" : "zh-CN";
      if (i18n.language !== resolved) void i18n.changeLanguage(resolved);
    }
    setTick((n) => n + 1);
  }, [lang, i18n]);

  return null;
}

/** 便捷：当前语言段（zh/en）。 */
export function useLocaleSegment(): string {
  const { locale } = useLocale();
  return localeSegment(locale);
}
