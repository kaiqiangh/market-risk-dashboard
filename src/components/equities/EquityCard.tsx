import { useTranslation } from "react-i18next";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatChange, formatMoney, formatNumber, formatPercentile } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { EquityAsset } from "@/schemas";

/**
 * EquityCard：关键美股卡（NVDA/AVGO/MU/AMD/TSLA，MVP 冻结 G2）。
 * 卡片级指标：价格/1d/1w/1m/RSI/MA50/MA200/5Y 百分位。
 */
export interface EquityCardProps {
  asset: EquityAsset;
}

export function EquityCard({ asset }: EquityCardProps) {
  const { t, i18n } = useTranslation("equities");
  const locale = i18n.language;
  const tone = changeTone(asset.change_1d);
  const classes = toneClasses(tone);
  const displayName = locale.startsWith("zh") && asset.name_zh ? asset.name_zh : asset.name;

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
              ["1W", asset.change_1w],
              ["1M", asset.change_1m],
              ["YTD", asset.change_ytd],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded bg-muted/50 px-1.5 py-1 text-center">
              <dt className="text-[9px] uppercase text-muted-foreground">{label}</dt>
              <dd className={`font-medium tabular-nums ${toneClasses(changeTone(value)).text}`}>
                {value === null ? t("common:data.na") : formatChange(value, locale)}
              </dd>
            </div>
          ))}
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] uppercase text-muted-foreground">RSI</dt>
            <dd className="font-medium tabular-nums">
              {asset.rsi14 === null ? t("common:data.na") : formatNumber(asset.rsi14, locale, 1)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] uppercase text-muted-foreground">MA50</dt>
            <dd className={`font-medium tabular-nums ${toneClasses(changeTone(asset.ma50_distance_pct)).text}`}>
              {asset.ma50_distance_pct === null ? t("common:data.na") : formatChange(asset.ma50_distance_pct, locale)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] uppercase text-muted-foreground">MA200</dt>
            <dd className={`font-medium tabular-nums ${toneClasses(changeTone(asset.ma200_distance_pct)).text}`}>
              {asset.ma200_distance_pct === null ? t("common:data.na") : formatChange(asset.ma200_distance_pct, locale)}
            </dd>
          </div>
          <div className="col-span-3 rounded bg-muted/50 px-1.5 py-1 text-center">
            <dt className="text-[9px] uppercase text-muted-foreground">{t("metric.percentile5y")}</dt>
            <dd className="font-medium tabular-nums">
              {asset.percentile_5y === null ? t("common:data.na") : formatPercentile(asset.percentile_5y, locale)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
