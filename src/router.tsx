import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LOCALES, type SupportedLocale } from "./i18n";

/**
 * 路由表（T01 骨架，8 个页面占位）。
 * 语言段驱动：`#/zh/overview` / `#/en/overview`（架构 §1.9）。
 * 页面组件在 T04 落地；此处 Placeholder 保证路由可访问、可部署。
 */
export const PAGE_KEYS = [
  "overview",
  "macro",
  "equities",
  "themes",
  "news",
  "calendar",
  "risklab",
  "status",
] as const;

export type PageKey = (typeof PAGE_KEYS)[number];

const PAGE_TITLE_KEYS: Record<PageKey, string> = {
  overview: "nav.overview",
  macro: "nav.macro",
  equities: "nav.equities",
  themes: "nav.themes",
  news: "nav.news",
  calendar: "nav.calendar",
  risklab: "nav.risklab",
  status: "nav.status",
};

function PlaceholderPage() {
  const { lang, page } = useParams<{ lang: string; page: string }>();
  const { t } = useTranslation("common");
  const titleKey = PAGE_TITLE_KEYS[page as PageKey] ?? "nav.overview";

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="text-2xl font-semibold text-foreground">{t(titleKey)}</h1>
      <p className="text-sm text-muted-foreground">
        {t("placeholder.route")} — <code className="rounded bg-muted px-1.5 py-0.5">{`#/${lang}/${page}`}</code>
      </p>
      <p className="text-xs text-muted-foreground">{t("placeholder.t04")}</p>
    </div>
  );
}

function NotFoundPage() {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="text-2xl font-semibold text-foreground">404</h1>
      <p className="text-sm text-muted-foreground">{t("placeholder.notFound")}</p>
    </div>
  );
}

function LocalePage() {
  const { lang } = useParams<{ lang: string }>();
  if (!SUPPORTED_LOCALES.includes(lang as SupportedLocale)) {
    return <Navigate to="/zh/overview" replace />;
  }
  return (
    <Routes>
      <Route index element={<Navigate to="overview" replace />} />
      {PAGE_KEYS.map((page) => (
        <Route key={page} path={page} element={<PlaceholderPage />} />
      ))}
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/zh/overview" replace />} />
      <Route path="/:lang" element={<LocalePage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
