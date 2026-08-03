import { lazy, type ComponentType, type LazyExoticComponent } from "react";
import { Navigate, Outlet, Route, Routes, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AppLayout } from "@/components/layout/AppLayout";

/**
 * 路由表（架构 §1.2 Hash Router + 路由懒加载）。
 * 语言段驱动：`#/zh/overview` / `#/en/overview`。
 * 页面组件 T04 落地（React.lazy 代码分割；Suspense fallback 在 AppLayout）。
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

const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const MacroPage = lazy(() => import("./pages/MacroPage"));
const EquitiesPage = lazy(() => import("./pages/EquitiesPage"));
const ThemesPage = lazy(() => import("./pages/ThemesPage"));
const NewsPage = lazy(() => import("./pages/NewsPage"));
const CalendarPage = lazy(() => import("./pages/CalendarPage"));
const RiskLabPage = lazy(() => import("./pages/RiskLabPage"));
const StatusPage = lazy(() => import("./pages/StatusPage"));

const PAGE_COMPONENTS: Record<PageKey, LazyExoticComponent<ComponentType>> = {
  overview: OverviewPage,
  macro: MacroPage,
  equities: EquitiesPage,
  themes: ThemesPage,
  news: NewsPage,
  calendar: CalendarPage,
  risklab: RiskLabPage,
  status: StatusPage,
};

function NotFoundPage() {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="text-2xl font-semibold text-foreground">404</h1>
      <p className="text-sm text-muted-foreground">{t("placeholder.notFound")}</p>
    </div>
  );
}

/** 语言段守卫：非法语言段 → 重定向默认页（URL 段为 zh/en，对应 zh-CN/en locale）。 */
function LangGuard() {
  const { lang } = useParams<{ lang?: string }>();
  if (lang !== "zh" && lang !== "en") {
    return <Navigate to="/zh/overview" replace />;
  }
  return <Outlet />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/zh/overview" replace />} />
      <Route path="/:lang" element={<AppLayout />}>
        <Route element={<LangGuard />}>
          <Route index element={<Navigate to="overview" replace />} />
          {PAGE_KEYS.map((page) => {
            const Component = PAGE_COMPONENTS[page];
            return <Route key={page} path={page} element={<Component />} />;
          })}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
