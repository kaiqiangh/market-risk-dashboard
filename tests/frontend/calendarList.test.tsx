import "./helpers/setTimezone"; // MUST be first: pins TZ before CalendarList is evaluated
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";
import { CalendarList } from "@/components/calendar/CalendarList";
import { groupByDate } from "@/lib/calendar";
import type { CalendarEvent } from "@/schemas";

/**
 * #94: events carry an unambiguous UTC instant; the UI groups by the LOCAL day of that
 * instant (an 08:30 ET release is 12:30Z but must land on the operator's local release
 * date, not shift a day for viewers east of UTC). TZ pinned to America/New_York.
 */

function ev(id: string, datetime: string): CalendarEvent {
  return {
    id,
    type: "economic",
    title: id,
    country: "US",
    datetime,
    importance: "high",
    actual: null,
    forecast: null,
    previous: null,
    unit: null,
    related_assets: [],
    source: "fred",
  };
}

describe("groupByDate", () => {
  it("groups by the local day, not the raw UTC date", () => {
    // 2026-08-12T23:30:00Z is 19:30 ET on the 12th but 07:30 on the 13th in UTC+8;
    // 2026-08-13T00:30:00Z is 20:30 ET on the 12th — all three land on the 12th locally.
    const groups = groupByDate([
      ev("a", "2026-08-12T12:30:00Z"),
      ev("b", "2026-08-12T23:30:00Z"),
      ev("c", "2026-08-13T00:30:00Z"),
    ]);
    expect(groups.map((g) => g.date)).toEqual(["2026-08-12"]);
    expect(groups[0].events.map((e) => e.id).sort()).toEqual(["a", "b", "c"]);
  });

  it("splits across local days and sorts chronologically", () => {
    const groups = groupByDate([
      ev("late-12th", "2026-08-12T23:30:00Z"),
      ev("morning-13th", "2026-08-13T11:00:00Z"),
    ]);
    expect(groups.map((g) => g.date)).toEqual(["2026-08-12", "2026-08-13"]);
  });
});

describe("CalendarList", () => {
  it("renders one section per local day with the events under it", () => {
    render(
      <CalendarList
        events={[
          ev("cpi", "2026-08-12T12:30:00Z"),
          ev("fomc", "2026-08-13T00:30:00Z"), // 20:30 ET on the 12th → same local section
        ]}
      />,
    );
    expect(screen.getAllByTestId("event-card")).toHaveLength(2);
    expect(screen.getByTestId("calendar-list")).toBeInTheDocument();
  });

  it("shows the empty state for no events", () => {
    render(<CalendarList events={[]} />);
    expect(screen.getByTestId("calendar-empty")).toBeInTheDocument();
  });
});
