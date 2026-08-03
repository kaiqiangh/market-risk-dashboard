import { useTranslation } from "react-i18next";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatChange, formatMoney, formatNumber } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import type { EquityAsset } from "@/schemas";

/**
 * AShareCard：A 股存储个股卡（移动端优先卡片；长表格改卡片，架构响应式要求）。
 */
export interface AShareCardProps {
  asset: EquityAsset;
}

export function AShareCard({ asset }: AShareCardProps) {
  const { t, i18n } = useTranslation("equities");
  const locale = i18n.language;
  const name = locale.startsWith("zh") && asset.name_zh ? asset.name_zh : asset.name;
  const tone = changeTone(asset.change_1d);
  const classes = toneClasses(tone);

  return (
    <Card data-testid="ashare-card">
      <CardHeader className="flex-row items-start justify-between gap-2">
        <div>
          <CardTitle className="font-mono text-xs">{asset.symbol}</CardTitle>
          <p className="text-sm font-medium text-foreground">{name}</p>
        </div>
        <div className="text-right">
          <p className="text-base font-bold tabular-nums">{formatMoney(asset.price, asset.currency, locale)}</p>
          <p className={`text-sm font-semibold tabular-nums ${classes.text}`}>
            {asset.change_1d === null ? t("common:data.na") : formatChange(asset.change_1d, locale)}
          </p>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-1.5 text-xs">
          <div className="rounded bg-muted/50 px-1.5 py-1">
            <dt className="text-[9px] uppercase text-muted-foreground">{t("metric.change1w")}</dt>
            <dd className={`font-medium tabular-nums ${toneClasses(changeTone(asset.change_1w)).text}`}>
              {asset.change_1w === null ? t("common:data.na") : formatChange(asset.change_1w, locale)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1">
            <dt className="text-[9px] uppercase text-muted-foreground">{t("metric.change1m")}</dt>
            <dd className={`font-medium tabular-nums ${toneClasses(changeTone(asset.change_1m)).text}`}>
              {asset.change_1m === null ? t("common:data.na") : formatChange(asset.change_1m, locale)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1">
            <dt className="text-[9px] uppercase text-muted-foreground">RSI</dt>
            <dd className="font-medium tabular-nums">
              {asset.rsi14 === null ? t("common:data.na") : formatNumber(asset.rsi14, locale, 1)}
            </dd>
          </div>
          <div className="rounded bg-muted/50 px-1.5 py-1">
            <dt className="text-[9px] uppercase text-muted-foreground">{t("metric.percentile5y")}</dt>
            <dd className="font-medium tabular-nums">
              {asset.percentile_5y === null ? t("common:data.na") : formatNumber(asset.percentile_5y, locale, 1)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}
