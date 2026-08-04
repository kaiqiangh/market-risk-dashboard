import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { NewsEnvelope } from "@/schemas";
import { NewsList } from "@/components/news/NewsList";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { formatNumber } from "@/lib/format";

/**
 * NewsPage: news page (top importance list).
 */
export default function NewsPage() {
  const { t, i18n } = useTranslation("news");
  const locale = i18n.language;
  const newsQ = useDataset<NewsEnvelope>("news");

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
        <NewsList items={newsQ.data.payload.items} />
      ) : (
        <EmptyState title={t("none")} />
      )}
    </div>
  );
}
