import { Link, NavLink, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { ComponentType } from "react";
import { LayoutDashboard, LineChart, Newspaper, BarChart3, CalendarDays, FlaskConical, Activity, CircleDollarSign } from "lucide-react";
import { PAGE_KEYS, type PageKey } from "@/router";
import { cn } from "@/lib/utils";
import { LanguageSwitch } from "./LanguageSwitch";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Navbar：顶部导航（架构 §1.9 语言段驱动；移动端横向滚动）。
 */

const PAGE_ICONS: Record<PageKey, ComponentType<{ className?: string }>> = {
  overview: LayoutDashboard,
  macro: LineChart,
  equities: CircleDollarSign,
  themes: BarChart3,
  news: Newspaper,
  calendar: CalendarDays,
  risklab: FlaskConical,
  status: Activity,
};

export function Navbar() {
  const { t } = useTranslation("common");
  const { lang } = useParams<{ lang?: string }>();
  const segment = lang === "en" ? "en" : "zh";

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4">
        <Link to={`/${segment}/overview`} className="flex shrink-0 items-center gap-2" data-testid="brand">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/15 text-primary" aria-hidden>
            <Activity className="h-4 w-4" />
          </span>
          <span className="hidden text-sm font-semibold sm:inline">{t("app.nameShort")}</span>
        </Link>

        <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label={t("nav.aria")}>
          {PAGE_KEYS.map((page) => (
            <NavLink
              key={page}
              to={`/${segment}/${page}`}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )
              }
            >
              {(() => {
                const Icon = PAGE_ICONS[page];
                return <Icon className="h-3.5 w-3.5" aria-hidden />;
              })()}
              <span>{t(`nav.${page}`)}</span>
            </NavLink>
          ))}
        </nav>

        <div className="flex shrink-0 items-center gap-1">
          <ThemeToggle />
          <LanguageSwitch />
        </div>
      </div>
    </header>
  );
}
