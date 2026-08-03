import { useTranslation } from "react-i18next";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatChange, formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * AssetCard: cross-asset / single-stock mini card (price + change; color + text + value).
 */
export interface AssetCardProps {
  symbol: string;
  name?: string | null;
  /** Primary value (price / index). */
  value?: number | null;
  change1d?: number | null;
  sub?: string | null;
  className?: string;
}

export function AssetCard({ symbol, name, value, change1d, sub, className }: AssetCardProps) {
  const { i18n } = useTranslation();
  const locale = i18n.language;
  const tone = changeTone(change1d);
  const classes = toneClasses(tone);

  return (
    <div
      className={cn("rounded-md border border-border bg-muted/40 px-3 py-2", className)}
      data-testid="asset-card"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">{symbol}</span>
        {value !== null && value !== undefined ? (
          <span className="text-sm font-medium tabular-nums text-muted-foreground">{formatNumber(value, locale)}</span>
        ) : null}
      </div>
      {name ? <p className="truncate text-[11px] text-muted-foreground">{name}</p> : null}
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className={cn("text-sm font-semibold tabular-nums", classes.text)}>
          {change1d === null || change1d === undefined ? "—" : formatChange(change1d, locale)}
        </span>
        {sub ? <span className="truncate text-[10px] text-muted-foreground">{sub}</span> : null}
      </div>
    </div>
  );
}
