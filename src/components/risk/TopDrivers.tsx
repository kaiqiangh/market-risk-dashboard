import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { RISK_DIMENSION_KEYS } from "@/lib/riskLabels";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatNumber, formatPctPoints } from "@/lib/format";
import type { DriverContribution, RiskDimensionKey } from "@/schemas";

/**
 * TopDrivers: top risk drivers (contribution to the total score).
 */
export interface TopDriversProps {
  drivers: DriverContribution[];
}

export function TopDrivers({ drivers }: TopDriversProps) {
  const { t, i18n } = useTranslation("risk");
  const locale = i18n.language;

  if (drivers.length === 0) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-muted-foreground" aria-hidden />
            {t("drivers.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState title={t("drivers.none")} />
        </CardContent>
      </Card>
    );
  }

  const top = [...drivers]
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    .slice(0, 5);

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-muted-foreground" aria-hidden />
          {t("drivers.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {top.map((driver, i) => {
          const tone = changeTone(driver.contribution);
          const classes = toneClasses(tone);
          return (
            <div
              key={`${driver.dimension_key}-${driver.indicator_key}`}
              className="flex items-center gap-3 rounded-md border border-border bg-muted/40 px-3 py-2"
              data-testid="risk-driver"
            >
              <span className="w-5 shrink-0 text-center text-xs font-semibold text-muted-foreground">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">{driver.label}</p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {t(RISK_DIMENSION_KEYS[driver.dimension_key as RiskDimensionKey])}
                </p>
              </div>
              <div className="shrink-0 text-right">
                <p className={`text-sm font-semibold tabular-nums ${classes.text}`}>
                  {formatNumber(driver.contribution, locale)}
                </p>
                {driver.change_1d !== null && driver.change_1d !== undefined ? (
                  <p className="text-[11px] tabular-nums text-muted-foreground">
                    {formatPctPoints(driver.change_1d, locale)}
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
