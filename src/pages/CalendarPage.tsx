import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { CalendarEnvelope } from "@/schemas";
import { CalendarList } from "@/components/calendar/CalendarList";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";

/**
 * CalendarPage：日历页（经济日历 + 财报日历，按日期分组）。
 */
export default function CalendarPage() {
  const { t } = useTranslation("calendar");
  const calendarQ = useDataset<CalendarEnvelope>("calendar");

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-bold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-sm text-muted-foreground">{t("subtitle")}</p>
        {calendarQ.data ? <StatusBadge status={calendarQ.data.freshness_status} withDescription /> : null}
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
