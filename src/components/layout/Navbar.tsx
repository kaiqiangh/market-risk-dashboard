import { Link, NavLink, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { ComponentType } from "react";
import {
  Activity,
  BarChart3,
  CalendarDays,
  CircleDollarSign,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  MoreHorizontal,
  Newspaper,
} from "lucide-react";
import { PAGE_KEYS, type PageKey } from "@/router";
import { cn } from "@/lib/utils";
import { LanguageSwitch } from "./LanguageSwitch";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Navbar: top navigation (architecture §1.9 language-segment driven).
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
  const directPages = new Set<PageKey>(["overview", "macro", "equities", "news"]);

  return (
    <header className="sticky top-0 z-40 border-b border-hairline bg-background">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-2 px-3 sm:gap-3 sm:px-4">
        <Link to={`/${segment}/overview`} className="flex shrink-0 items-center gap-2" data-testid="brand">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/15 text-primary" aria-hidden>
            <Activity className="h-4 w-4" />
          </span>
          <span className="hidden text-sm font-semibold sm:inline">{t("app.nameShort")}</span>
        </Link>

        <nav className="flex min-w-0 flex-1 items-center gap-0.5 sm:gap-1" aria-label={t("nav.aria")}>
          {PAGE_KEYS.map((page) => (
            <NavLink
              key={page}
              to={`/${segment}/${page}`}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-1 rounded-md px-1.5 py-2 text-[11px] font-medium transition-colors sm:gap-1.5 sm:px-2.5 sm:py-1.5 sm:text-xs",
                  !directPages.has(page) && "hidden sm:flex",
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
          <details className="relative sm:hidden">
            <summary className="flex min-h-10 cursor-pointer list-none items-center gap-1 rounded-md px-1.5 py-2 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground [&::-webkit-details-marker]:hidden">
              <MoreHorizontal className="h-4 w-4" aria-hidden />
              <span>{t("nav.more")}</span>
            </summary>
            <div className="absolute left-0 top-full z-50 mt-1 min-w-40 rounded-md border border-border bg-popover p-1 shadow-lg">
              {PAGE_KEYS.filter((page) => !directPages.has(page)).map((page) => {
                const Icon = PAGE_ICONS[page];
                return (
                  <NavLink
                    key={page}
                    to={`/${segment}/${page}`}
                    className={({ isActive }) =>
                      cn(
                        "flex min-h-10 items-center gap-2 rounded px-2 py-2 text-xs font-medium",
                        isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )
                    }
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    <span>{t(`nav.${page}`)}</span>
                  </NavLink>
                );
              })}
            </div>
          </details>
        </nav>

        <div className="flex shrink-0 items-center gap-1">
          <ThemeToggle />
          <LanguageSwitch />
        </div>
      </div>
    </header>
  );
}
