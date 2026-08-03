import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { CalendarEnvelope } from "@/schemas";
import { CalendarList } from "@/components/calendar/CalendarList";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

/**
 * CalendarPage: calendar page (economic calendar + earnings calendar, grouped by date).
 */
export default function CalendarPage() {
  const { t } = useTranslation("calendar");
  const calendarQ = useDataset<CalendarEnvelope>("calendar");

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {calendarQ.data ? <span className="ml-auto"><StatusBadge status={calendarQ.data.freshness_status} withDescription /></span> : null}
      </header>

      {calendarQ.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : calendarQ.isError ? (
        <ErrorState onRetry={calendarQ.refetch} />
      ) : calendarQ.data ? (
        <CalendarList events={calendarQ.data.payload.events} />
      ) : (
        <EmptyState title={t("none")} />
      )}
    </div>
  );
}
