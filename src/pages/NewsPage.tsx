import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { NewsEnvelope } from "@/schemas";
import { NewsList } from "@/components/news/NewsList";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * NewsPage: news page (top importance list + client-side importance filter).
 */
type NewsFilter = "all" | "high" | "mediumPlus";

const NEWS_FILTERS: NewsFilter[] = ["all", "high", "mediumPlus"];

/** Thresholds mirror ImportanceBadge (high ≥ 70, medium ≥ 40). */
const SESSION_KEY = "mrd:news-filter";

export default function NewsPage() {
  const { t, i18n } = useTranslation("news");
  const locale = i18n.language;
  const newsQ = useDataset<NewsEnvelope>("news");

  const [filter, setFilter] = useState<NewsFilter>(() => {
    const stored = typeof sessionStorage !== "undefined" ? sessionStorage.getItem(SESSION_KEY) : null;
    return stored === "high" || stored === "mediumPlus" ? stored : "all";
  });
  useEffect(() => {
    sessionStorage.setItem(SESSION_KEY, filter);
  }, [filter]);

  const allItems = newsQ.data?.payload.items ?? [];
  const filtered = allItems.filter((item) => {
    if (filter === "all") return true;
    if (filter === "high") return item.importance >= 70;
    return item.importance >= 40;
  });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {newsQ.data ? (
          <div className="ml-auto flex items-center gap-3">
            <StatusBadge status={newsQ.data.freshness_status} fromCache={newsQ.data.provenance?.from_cache} />
            <span className="text-xs text-muted-foreground">
              {t("total")}: {formatNumber(newsQ.data.payload.total, locale)}
            </span>
          </div>
        ) : null}
      </header>

      {newsQ.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : newsQ.isError ? (
        <ErrorState onRetry={newsQ.refetch} />
      ) : newsQ.data ? (
        <div className="flex flex-col gap-4">
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label={t("filter.label")}
            data-testid="news-filter"
          >
            {NEWS_FILTERS.map((key) => {
              const active = filter === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  aria-pressed={active}
                  className={cn(
                    "rounded-full border px-2.5 py-1 text-xs min-h-[28px] transition-colors",
                    active
                      ? "border-fresh-ok/40 bg-fresh-ok/10 text-fresh-ok"
                      : "border-hairline text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t(`filter.${key}`)}
                </button>
              );
            })}
          </div>
          <NewsList items={filtered} />
        </div>
      ) : (
        <EmptyState title={t("none")} />
      )}
    </div>
  );
}
