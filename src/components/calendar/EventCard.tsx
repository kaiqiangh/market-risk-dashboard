import { useTranslation } from "react-i18next";
import { Briefcase, Landmark } from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatDateTime, formatUnitSuffix } from "@/lib/format";
import { displayEventTitle } from "@/lib/displayLanguage";
import type { CalendarEvent } from "@/schemas";

/**
 * EventCard: calendar event card (economic / earnings; importance color + text; actual / forecast / previous).
 */
export interface EventCardProps {
  event: CalendarEvent;
}

function EventIcon({ type }: { type: CalendarEvent["type"] }) {
  if (type === "earnings") return <Briefcase className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
  return <Landmark className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />;
}

const IMPORTANCE_VARIANT = {
  high: "high",
  medium: "caution",
  low: "secondary",
} as const;

export function EventCard({ event }: EventCardProps) {
  const { t, i18n } = useTranslation("calendar");
  const locale = i18n.language;
  const valueWithUnit = (value: number | null) => value === null ? t("common:data.na") : `${value}${formatUnitSuffix(event.unit ?? "", locale)}`;

  return (
    <Card data-testid="event-card">
      <CardContent className="flex flex-col gap-1.5 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <EventIcon type={event.type} />
            <span>{t(`type.${event.type}`)}</span>
            <Badge variant={IMPORTANCE_VARIANT[event.importance]} className="px-1.5 py-0 text-xs">
              {t(`importance.${event.importance}`)}
            </Badge>
          </div>
          <span className="text-xs text-muted-foreground">{formatDateTime(event.datetime, locale)}</span>
        </div>
        <p className="text-base font-medium text-foreground">{displayEventTitle(event.title, locale)}</p>
        <dl className="grid grid-cols-3 gap-1.5 text-xs">
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-xs uppercase text-muted-foreground">{t("field.actual")}</dt>
            <dd className="tabular-nums">{valueWithUnit(event.actual)}</dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-xs uppercase text-muted-foreground">{t("field.forecast")}</dt>
            <dd className="tabular-nums">{valueWithUnit(event.forecast)}</dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-xs uppercase text-muted-foreground">{t("field.previous")}</dt>
            <dd className="tabular-nums">{valueWithUnit(event.previous)}</dd>
          </div>
        </dl>
        {event.related_assets.length > 0 ? (
          <div className="flex flex-wrap gap-1 text-xs text-muted-foreground">
            {event.related_assets.map((a) => (
              <span key={a} className="rounded bg-muted px-1.5 py-0.5 font-mono">
                {a}
              </span>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
