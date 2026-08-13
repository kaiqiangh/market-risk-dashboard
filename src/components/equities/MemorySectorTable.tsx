import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { EmptyState } from "@/components/ui/EmptyState";
import { dirTone, dirClasses } from "@/lib/riskColors";
import { formatChange, formatMoney } from "@/lib/format";
import type { EquityAsset, MemoryProxy } from "@/schemas";
import { displayLocalizedValue } from "@/lib/displayLanguage";
import { cn } from "@/lib/utils";

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

  type SortKey = "change_1d" | "change_1w" | "change_1m";
  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sortedAssets = useMemo(() => {
    if (!sortKey) return assets;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...assets].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null && bv === null) return 0;
      if (av === null) return 1; // nulls always last
      if (bv === null) return -1;
      return (av - bv) * dir;
    });
  }, [assets, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortColumns = [
    { field: "change_1d" as SortKey, labelKey: "change1d" },
    { field: "change_1w" as SortKey, labelKey: "change1w" },
    { field: "change_1m" as SortKey, labelKey: "change1m" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("memory.title")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {memory ? (
          <div className="rounded-md border border-border bg-muted/40 p-3">
            <p className="text-xs font-medium text-foreground">
              {displayLocalizedValue(memory.label, memory.label_zh, locale)}
            </p>
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
              <span>
                {t("memory.change1w")}:{" "}
                <span className={dirClasses(dirTone(memory.change_1w)).text}>
                  {memory.change_1w === null ? t("common:data.na") : formatChange(memory.change_1w, locale)}
                </span>
              </span>
              <span>
                {t("memory.change1m")}:{" "}
                <span className={dirClasses(dirTone(memory.change_1m)).text}>
                  {memory.change_1m === null ? t("common:data.na") : formatChange(memory.change_1m, locale)}
                </span>
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{t("memory.note")}</p>
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
                <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 pr-2 font-medium">{t("table.symbol")}</th>
                  <th className="py-1.5 pr-2 font-medium">{t("table.name")}</th>
                  <th className="py-1.5 pr-2 text-right font-medium">{t("table.price")}</th>
                  {sortColumns.map(({ field, labelKey }) => {
                    const active = sortKey === field;
                    const Icon = active ? (sortDir === "asc" ? ChevronUp : ChevronDown) : ChevronsUpDown;
                    return (
                      <th
                        key={field}
                        className="py-1.5 pr-2 text-right font-medium"
                        aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}
                      >
                        <button
                          type="button"
                          onClick={() => toggleSort(field)}
                          aria-label={`${t("sort.activate")} ${t(`table.${labelKey}`)}`}
                          className="inline-flex items-center gap-1 hover:text-foreground"
                        >
                          <span>{t(`table.${labelKey}`)}</span>
                          <Icon className={cn("h-3 w-3", active ? "text-fresh-ok" : "text-muted-foreground/60")} aria-hidden />
                        </button>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sortedAssets.map((a) => {
                  const name = displayLocalizedValue(a.name, a.name_zh, locale);
                  return (
                    <tr key={a.symbol} className="border-b border-border/50 last:border-0 hover:bg-[rgba(107,163,201,0.07)]">
                      <td className="py-1.5 pr-2 font-mono text-foreground">{a.symbol}</td>
                      <td className="py-1.5 pr-2">{name}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{formatMoney(a.price, a.currency, locale)}</td>
                      <td className={`py-1.5 pr-2 text-right tabular-nums ${dirClasses(dirTone(a.change_1d)).text}`}>
                        {a.change_1d === null ? t("common:data.na") : formatChange(a.change_1d, locale)}
                      </td>
                      <td className={`py-1.5 pr-2 text-right tabular-nums ${dirClasses(dirTone(a.change_1w)).text}`}>
                        {a.change_1w === null ? t("common:data.na") : formatChange(a.change_1w, locale)}
                      </td>
                      <td className={`py-1.5 text-right tabular-nums ${dirClasses(dirTone(a.change_1m)).text}`}>
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
