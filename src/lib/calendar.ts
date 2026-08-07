import type { CalendarEvent } from "@/schemas";

/**
 * Calendar grouping by LOCAL day (#94).
 *
 * Events carry an unambiguous UTC instant (e.g. an 08:30 ET release is 12:30Z). The UI
 * must group on the operator's *local* day of that instant — grouping on the raw UTC
 * date shifts a release a day for viewers east of UTC. Kept out of the component file
 * so CalendarList stays a pure component module (react-refresh).
 */

/** Local-day key (`YYYY-MM-DD`) of a UTC event instant. */
export function localDayKey(datetime: string): string {
  const local = new Date(datetime);
  return `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, "0")}-${String(local.getDate()).padStart(2, "0")}`;
}

export function groupByDate(events: CalendarEvent[]): Array<{ date: string; events: CalendarEvent[] }> {
  const map = new Map<string, CalendarEvent[]>();
  for (const ev of events) {
    const key = localDayKey(ev.datetime);
    const list = map.get(key) ?? [];
    list.push(ev);
    map.set(key, list);
  }
  return Array.from(map.entries())
    .map(([date, list]) => ({ date, events: list }))
    .sort((a, b) => a.date.localeCompare(b.date));
}
