import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { changeTone, toneClasses } from "@/lib/riskColors";
import { formatChange, formatMoney } from "@/lib/format";
import type { EquityAsset, MemoryProxy } from "@/schemas";

/**
 * MemorySectorTable: memory sector (Micron + A-share memory, architecture §8.10 pool).
 * Shows a degraded notice + available data when T03 is degraded (A-share collection failure).
 */
export interface MemorySectorTableProps {
  assets: EquityAsset[];
  memory: MemoryProxy | null;
}

export function MemorySectorTable({ assets, memory }: MemorySectorTableProps) {
  const { t, i18n } = useTranslation("equities");
  const locale = i18n.language;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("memory.title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {memory ? (
          <div className="rounded-md border border-border bg-muted/40 p-3">
            <p className="text-xs font-medium text-foreground">
              {locale.startsWith("zh") && memory.label_zh ? memory.label_zh : memory.label}
            </p>
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
              <span>
                {t("memory.change1w")}:{" "}
                <span className={toneClasses(changeTone(memory.change_1w)).text}>
                  {memory.change_1w === null ? t("common:data.na") : formatChange(memory.change_1w, locale)}
                </span>
              </span>
              <span>
                {t("memory.change1m")}:{" "}
                <span className={toneClasses(changeTone(memory.change_1m)).text}>
                  {memory.change_1m === null ? t("common:data.na") : formatChange(memory.change_1m, locale)}
                </span>
              </span>
            </div>
            {memory.note ? <p className="mt-1 text-[10px] text-muted-foreground">{memory.note}</p> : null}
          </div>
        ) : null}

        {assets.length === 0 ? (
          <div className="flex flex-col gap-2">
            <Badge variant="caution" className="w-fit">
              {t("memory.degraded")}
            </Badge>
            <EmptyState title={t("memory.empty")} />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-xs">
              <thead>
                <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 pr-2 font-medium">{t("table.symbol")}</th>
                  <th className="py-1.5 pr-2 font-medium">{t("table.name")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("table.price")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("table.change1d")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("table.change1w")}</th>
                  <th className="py-1.5 text-right font-medium">{t("table.change1m")}</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((a) => {
                  const name = locale.startsWith("zh") && a.name_zh ? a.name_zh : a.name;
                  return (
                    <tr key={a.symbol} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5 pr-2 font-mono text-foreground">{a.symbol}</td>
                      <td className="py-1.5 pr-2">{name}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{formatMoney(a.price, a.currency, locale)}</td>
                      <td className={`py-1.5 pr-2 text-right tabular-nums ${toneClasses(changeTone(a.change_1d)).text}`}>
                        {a.change_1d === null ? t("common:data.na") : formatChange(a.change_1d, locale)}
                      </td>
                      <td className={`py-1.5 pr-2 text-right tabular-nums ${toneClasses(changeTone(a.change_1w)).text}`}>
                        {a.change_1w === null ? t("common:data.na") : formatChange(a.change_1w, locale)}
                      </td>
                      <td className={`py-1.5 text-right tabular-nums ${toneClasses(changeTone(a.change_1m)).text}`}>
                        {a.change_1m === null ? t("common:data.na") : formatChange(a.change_1m, locale)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
