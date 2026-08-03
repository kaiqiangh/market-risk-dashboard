import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { CalendarClock } from "lucide-react";
import { EventCard } from "./EventCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate } from "@/lib/format";
import type { CalendarEvent } from "@/schemas";

/**
 * CalendarList：日历列表（按日期分组；移动端单列卡片）。
 */
export interface CalendarListProps {
  events: CalendarEvent[];
}

function groupByDate(events: CalendarEvent[]): Array<{ date: string; events: CalendarEvent[] }> {
  const map = new Map<string, CalendarEvent[]>();
  for (const ev of events) {
    const key = ev.datetime.slice(0, 10); // YYYY-MM-DD
    const list = map.get(key) ?? [];
    list.push(ev);
    map.set(key, list);
  }
  return Array.from(map.entries())
    .map(([date, list]) => ({ date, events: list }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function CalendarList({ events }: CalendarListProps) {
  const { t, i18n } = useTranslation("calendar");
  const locale = i18n.language;
  const groups = useMemo(() => groupByDate(events), [events]);

  if (events.length === 0) {
    return <EmptyState title={t("none")} data-testid="calendar-empty" />;
  }

  return (
    <div className="flex flex-col gap-4" data-testid="calendar-list">
      {groups.map((group) => (
        <section key={group.date}>
          <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-foreground">
            <CalendarClock className="h-4 w-4 text-muted-foreground" aria-hidden />
            {formatDate(group.date, locale)}
          </h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {group.events.map((ev) => (
              <EventCard key={ev.id} event={ev} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
