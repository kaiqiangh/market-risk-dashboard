import { Link, NavLink, useLocation, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState, type ComponentType } from "react";
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
  const location = useLocation();
  const segment = lang === "en" ? "en" : "zh";
  const directPages = new Set<PageKey>(["overview", "macro", "equities", "news"]);
  const morePages = PAGE_KEYS.filter((page) => !directPages.has(page));
  const moreActive = morePages.some((page) => location.pathname.endsWith(`/${page}`));
  const [moreOpen, setMoreOpen] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMoreOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!moreOpen) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (!moreRef.current?.contains(event.target as Node)) setMoreOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMoreOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [moreOpen]);

  return (
    <header className="sticky top-0 z-40 border-b border-hairline bg-background">
      <div className="mx-auto flex min-h-14 max-w-[1440px] flex-wrap items-center gap-2 px-3 sm:h-14 sm:flex-nowrap sm:gap-3 sm:px-4">
        <Link to={`/${segment}/overview`} className="flex shrink-0 items-center gap-2" data-testid="brand">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/15 text-primary" aria-hidden>
            <Activity className="h-4 w-4" />
          </span>
          <span className="hidden text-sm font-semibold sm:inline">{t("app.nameShort")}</span>
        </Link>

        <nav className="order-last flex basis-full items-center gap-0 sm:order-none sm:min-w-0 sm:flex-1 sm:basis-auto sm:gap-1" aria-label={t("nav.aria")}>
          {PAGE_KEYS.map((page) => (
            <NavLink
              key={page}
              to={`/${segment}/${page}`}
              className={({ isActive }) =>
                cn(
                  "flex min-h-11 shrink-0 items-center gap-1 rounded-md px-1 py-2 text-xs font-medium transition-colors sm:min-h-0 sm:gap-1.5 sm:px-2.5 sm:py-1.5 sm:text-xs",
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
          <div ref={moreRef} className="relative sm:hidden">
            <button
              type="button"
              className={cn(
                "flex min-h-11 items-center gap-1 rounded-md px-1 py-2 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground",
                moreActive && "bg-primary/10 text-primary",
              )}
              aria-expanded={moreOpen}
              aria-haspopup="menu"
              aria-current={moreActive ? "page" : undefined}
              aria-label={moreActive ? `${t("nav.more")} (${t("nav.current")})` : t("nav.more")}
              onClick={() => setMoreOpen((open) => !open)}
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden />
              <span>{t("nav.more")}</span>
            </button>
            {moreOpen ? <div className="absolute left-0 top-full z-50 mt-1 min-w-40 rounded-md border border-border bg-popover p-1 shadow-lg" role="menu">
              {morePages.map((page) => {
                const Icon = PAGE_ICONS[page];
                return (
                  <NavLink
                    key={page}
                    to={`/${segment}/${page}`}
                    className={({ isActive }) =>
                      cn(
                        "flex min-h-11 items-center gap-2 rounded px-2 py-2 text-xs font-medium",
                        isActive ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )
                    }
                    role="menuitem"
                    onClick={() => setMoreOpen(false)}
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    <span>{t(`nav.${page}`)}</span>
                  </NavLink>
                );
              })}
            </div>
            : null}
          </div>
        </nav>

        <div className="flex shrink-0 items-center gap-1">
          <ThemeToggle />
          <LanguageSwitch />
        </div>
      </div>
    </header>
  );
}
