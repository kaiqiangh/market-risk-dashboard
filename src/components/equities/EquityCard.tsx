import { useTranslation } from "react-i18next";
import { dirTone, dirClasses } from "@/lib/riskColors";
import { formatChange, formatMoney, formatNumber, formatPercentile } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { EquityAsset } from "@/schemas";
import { displayLocalizedValue } from "@/lib/displayLanguage";

/**
 * EquityCard: key US equities card (NVDA/AVGO/MU/AMD/TSLA, frozen for MVP G2).
 * Card-level indicators: price / 1d / 1w / 1m / RSI / MA50 / MA200 / 1Y percentile.
 */
export interface EquityCardProps {
  asset: EquityAsset;
}

export function EquityCard({ asset }: EquityCardProps) {
  const { t, i18n } = useTranslation("equities");
  const locale = i18n.language;
  const tone = dirTone(asset.change_1d);
  const classes = dirClasses(tone);
  const displayName = displayLocalizedValue(asset.name, asset.name_zh, locale);

  return (
    <Card data-testid="equity-card">
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="flex items-center gap-2">
            <span className="font-mono">{asset.symbol}</span>
            {asset.is_proxy ? (
              <Badge variant="outline" className="px-1 py-0 text-[9px]">
                {t("metric.proxy")}
              </Badge>
            ) : null}
          </CardTitle>
          <p className="text-[11px] text-muted-foreground">{displayName}</p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold tabular-nums">{formatMoney(asset.price, asset.currency, locale)}</p>
          <p className={`text-sm font-semibold tabular-nums ${classes.text}`}>
            {asset.change_1d === null ? t("common:data.na") : formatChange(asset.change_1d, locale)}
          </p>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-3 gap-x-2 gap-y-1.5 text-xs">
          {(
            [
              [t("metric.change1w"), asset.change_1w],
              [t("metric.change1m"), asset.change_1m],
              [t("metric.changeYtd"), asset.change_ytd],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded bg-muted/50 px-1.5 py-1 text-center">
              <dt className="text-[9px] uppercase text-muted-foreground">{label}</dt>
              <dd className={`font-medium tabular-nums ${dirClasses(dirTone(value)).text}`}>
                {value === null ? t("common:data.na") : formatChange(value, locale)}
              </dd>
            </div>
          ))}
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] text-muted-foreground">{t("metric.rsi14")}</dt>
            <dd className="font-medium tabular-nums">
              {asset.rsi14 === null ? t("common:data.na") : formatNumber(asset.rsi14, locale, 1)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] text-muted-foreground">{t("metric.ma50")}</dt>
            <dd className={`font-medium tabular-nums ${dirClasses(dirTone(asset.ma50_distance_pct)).text}`}>
              {asset.ma50_distance_pct === null ? t("common:data.na") : formatChange(asset.ma50_distance_pct, locale)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] text-muted-foreground">{t("metric.ma200")}</dt>
            <dd className={`font-medium tabular-nums ${dirClasses(dirTone(asset.ma200_distance_pct)).text}`}>
              {asset.ma200_distance_pct === null ? t("common:data.na") : formatChange(asset.ma200_distance_pct, locale)}
            </dd>
          </div>
          <div className="col-span-3 rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] uppercase text-muted-foreground">{t("metric.percentile1y")}</dt>
            <dd className="font-medium tabular-nums">
              {asset.percentile_1y === null ? t("common:data.na") : formatPercentile(asset.percentile_1y, locale)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
