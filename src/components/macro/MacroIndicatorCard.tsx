import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { StatusBadge } from "@/components/layout/StatusBadge";
import { formatDateTime, formatNumber, formatUnitSuffix } from "@/lib/format";
import type { MacroIndicator } from "@/schemas";

/**
 * MacroIndicatorCard：宏观指标卡（数值 + 单位 + 环比 + freshness）。
 */
export interface MacroIndicatorCardProps {
  indicator: MacroIndicator;
}

export function MacroIndicatorCard({ indicator }: MacroIndicatorCardProps) {
  const { t, i18n } = useTranslation("macro");
  const locale = i18n.language;

  return (
    <Card className="h-full" data-testid="macro-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-xs">{indicator.label}</CardTitle>
        <StatusBadge status={indicator.status} />
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <p className="text-2xl font-bold tabular-nums">
          {indicator.value === null ? t("common:data.na") : formatNumber(indicator.value, locale)}
          {indicator.value !== null ? <span className="ml-1 text-xs font-normal text-muted-foreground">{formatUnitSuffix(indicator.unit, locale)}</span> : null}
        </p>
        <p className="text-xs text-muted-foreground">
          {indicator.change_1m === null || indicator.change_1m === undefined
            ? t("common:data.na")
            : `${t("indicator.change1m")} ${indicator.change_1m > 0 ? "+" : ""}${formatNumber(indicator.change_1m, locale)}${formatUnitSuffix(indicator.unit, locale)}`}
        </p>
        {indicator.updated_at ? (
          <p className="text-[10px] text-muted-foreground">{formatDateTime(indicator.updated_at, locale)}</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
