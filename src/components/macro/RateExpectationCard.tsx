import { useTranslation } from "react-i18next";
import { CalendarClock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Progress } from "@/components/ui/Progress";
import { Badge } from "@/components/ui/Badge";
import { formatDateTime, formatRatio } from "@/lib/format";
import type { FedWatchSnapshot } from "@/schemas";

/**
 * RateExpectationCard: FedWatch rate expectations (computed with CME methodology, architecture §1.6).
 * Free settlement history < 7 days → "insufficient data (accumulating)", do not show 0/empty values (frozen constraint).
 */
export interface RateExpectationCardProps {
  fedwatch: FedWatchSnapshot | null;
}

export function RateExpectationCard({ fedwatch }: RateExpectationCardProps) {
  const { t, i18n } = useTranslation("macro");
  const locale = i18n.language;

  if (!fedwatch || fedwatch.inferred_action === "insufficient_data" || fedwatch.status === "accumulating") {
    return (
      <Card className="h-full" data-testid="fedwatch-insufficient">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-muted-foreground" aria-hidden />
            {t("fedwatch.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-dashed border-border bg-muted/40 p-4 text-center">
            <p className="text-sm font-medium text-foreground">{t("fedwatch.insufficientData")}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t("fedwatch.accumulating")}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="h-full" data-testid="fedwatch-ready">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <CalendarClock className="h-4 w-4 text-muted-foreground" aria-hidden />
          {t("fedwatch.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-md bg-muted/50 p-2">
            <p className="text-muted-foreground">{t("fedwatch.meeting")}</p>
            <p className="text-sm font-semibold">
              {fedwatch.meeting_date ? formatDateTime(fedwatch.meeting_date, locale) : t("common:data.na")}
            </p>
          </div>
          <div className="rounded-md bg-muted/50 p-2">
            <p className="text-muted-foreground">{t("fedwatch.effectiveRate")}</p>
            <p className="text-sm font-semibold tabular-nums">{formatRatio(fedwatch.effective_rate / 100, locale)}</p>
          </div>
        </div>

        <p className="text-xs font-medium text-muted-foreground">{t("fedwatch.action")}:</p>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{t(`fedwatch.${fedwatch.inferred_action ?? "hold"}`)}</Badge>
        </div>

        {fedwatch.probabilities.length > 0 ? (
          <div className="flex flex-col gap-2">
            {fedwatch.probabilities.map((p) => (
              <div key={p.target_rate} className="flex items-center gap-2 text-xs">
                <span className="w-16 shrink-0 tabular-nums text-foreground">{formatRatio(p.target_rate / 100, locale)}</span>
                <Progress value={p.probability * 100} barClassName="bg-primary" className="h-2 flex-1" />
                <span className="w-12 shrink-0 text-right tabular-nums text-muted-foreground">{formatRatio(p.probability, locale)}</span>
              </div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
