import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useDataset } from "@/hooks/useDataset";
import type { CalendarEnvelope, CalendarEvent } from "@/schemas";
import { CalendarList } from "@/components/calendar/CalendarList";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { cn } from "@/lib/utils";

/**
 * CalendarPage: calendar page (economic calendar + earnings calendar, grouped by date).
 * Event-type filter is data-driven: chips are derived from the distinct types present
 * in the dataset (currently economic / earnings; FOMC is supported if it appears).
 */
export default function CalendarPage() {
  const { t } = useTranslation("calendar");
  const calendarQ = useDataset<CalendarEnvelope>("calendar");
  const [filter, setFilter] = useState<"all" | CalendarEvent["type"]>("all");

  const events = useMemo(() => calendarQ.data?.payload.events ?? [], [calendarQ.data]);
  const types = useMemo(() => Array.from(new Set(events.map((e) => e.type))), [events]);
  const filtered = filter === "all" ? events : events.filter((e) => e.type === filter);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-lg font-semibold text-foreground" data-testid="page-title">
          {t("title")}
        </h1>
        <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
        {calendarQ.data ? <span className="ml-auto"><StatusBadge status={calendarQ.data.freshness_status} fromCache={calendarQ.data.provenance?.from_cache} withDescription /></span> : null}
      </header>

      {calendarQ.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : calendarQ.isError ? (
        <ErrorState onRetry={calendarQ.refetch} />
      ) : calendarQ.data ? (
        <div className="flex flex-col gap-4">
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label={t("filter.label")}
            data-testid="calendar-filter"
          >
            <button
              type="button"
              onClick={() => setFilter("all")}
              aria-pressed={filter === "all"}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs min-h-[28px] transition-colors",
                filter === "all"
                  ? "border-fresh-ok/40 bg-fresh-ok/10 text-fresh-ok"
                  : "border-hairline text-muted-foreground hover:text-foreground",
              )}
            >
              {t("filter.all")}
            </button>
            {types.map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setFilter(type)}
                aria-pressed={filter === type}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs min-h-[28px] transition-colors",
                  filter === type
                    ? "border-fresh-ok/40 bg-fresh-ok/10 text-fresh-ok"
                    : "border-hairline text-muted-foreground hover:text-foreground",
                )}
              >
                {t(`type.${type}`, { defaultValue: type })}
              </button>
            ))}
          </div>
          <CalendarList events={filtered} />
        </div>
      ) : (
        <EmptyState title={t("none")} />
      )}
    </div>
  );
}
