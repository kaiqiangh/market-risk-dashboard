import { useTranslation } from "react-i18next";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatChange } from "@/lib/format";

/**
 * AssetHeatmap: category-first cross-asset change grid.
 * Each cell keeps the signed change and a localized direction state visible, so the
 * surface remains readable without hover, chart axes, or color perception.
 */
export interface HeatmapCell {
  asset: string;
  category: string;
  change1d: number | null;
}

export interface AssetHeatmapProps {
  cells: HeatmapCell[];
}

type HeatmapState = "up" | "down" | "flat" | "unavailable";

function stateFor(change: number | null): HeatmapState {
  if (change === null || !Number.isFinite(change)) return "unavailable";
  if (change > 0) return "up";
  if (change < 0) return "down";
  return "flat";
}

const STATE_CLASSES: Record<HeatmapState, string> = {
  up: "border-dir-up/40 bg-dir-up/10",
  down: "border-dir-down/40 bg-dir-down/10",
  flat: "border-border bg-muted/40",
  unavailable: "border-border/70 bg-muted/20",
};

const STATE_TEXT_CLASSES: Record<HeatmapState, string> = {
  up: "text-dir-up",
  down: "text-dir-down",
  flat: "text-muted-foreground",
  unavailable: "text-muted-foreground",
};

export function AssetHeatmap({ cells }: AssetHeatmapProps) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const groups = Array.from(
    cells.reduce((grouped, cell) => {
      const category = cell.category.trim() || t("heatmap.unknownCategory");
      const existing = grouped.get(category) ?? [];
      existing.push(cell);
      grouped.set(category, existing);
      return grouped;
    }, new Map<string, HeatmapCell[]>()),
  );

  if (cells.length === 0) {
    return <EmptyState title={t("heatmap.empty")} data-testid="chart-empty" />;
  }

  return (
    <div className="flex flex-col gap-3" data-testid="asset-heatmap">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground" data-testid="heatmap-legend">
        <span className="font-medium text-foreground">{t("heatmap.legend")}</span>
        {(["up", "down", "flat", "unavailable"] as const).map((state) => (
          <span key={state} className="inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-2.5 rounded-sm border ${STATE_CLASSES[state]}`} aria-hidden />
            {t(`heatmap.state.${state}`)}
          </span>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {groups.map(([category, categoryCells], categoryIndex) => (
          <section key={category} className="rounded-md border border-border/70 bg-surface-2/20 p-2.5" data-testid="heatmap-category">
            <header className="mb-2 flex items-baseline justify-between gap-2 border-b border-border/60 pb-1.5">
              <h3 className="text-xs font-semibold text-foreground">{category}</h3>
              <span className="text-[10px] tabular-nums text-muted-foreground">
                {t("heatmap.assetsCount", { count: categoryCells.length })}
              </span>
            </header>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid={`heatmap-category-grid-${categoryIndex}`}>
              {categoryCells.map((cell, cellIndex) => {
                const state = stateFor(cell.change1d);
                const asset = cell.asset.trim() || t("common:empty.translationUnavailable");
                const change = state === "unavailable" ? t("heatmap.state.unavailable") : formatChange(cell.change1d, locale);
                return (
                  <div
                    key={`${category}-${cell.asset}-${cellIndex}`}
                    className={`flex min-h-20 flex-col justify-between rounded-md border p-2.5 ${STATE_CLASSES[state]}`}
                    data-testid="heatmap-cell"
                    data-state={state}
                    aria-label={`${asset}: ${change}`}
                  >
                    <span className="break-words font-mono text-xs font-semibold text-foreground">{asset}</span>
                    <span className={`mt-2 text-sm font-semibold tabular-nums ${STATE_TEXT_CLASSES[state]}`}>{change}</span>
                    <span className="mt-0.5 text-[10px] text-muted-foreground">{t(`heatmap.state.${state}`)}</span>
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>

      <details className="rounded-md border border-border px-3 py-2 text-xs" data-testid="heatmap-details">
        <summary className="cursor-pointer font-medium text-muted-foreground">{t("heatmap.details")}</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 pr-2 font-medium">{t("heatmap.asset")}</th>
                <th className="py-1.5 pr-2 font-medium">{t("heatmap.axis")}</th>
                <th className="py-1.5 text-right font-medium">{t("heatmap.change")}</th>
              </tr>
            </thead>
            <tbody>
              {cells.map((cell, index) => {
                const state = stateFor(cell.change1d);
                return (
                  <tr key={`${cell.category}-${cell.asset}-${index}`} className="border-b border-border/50 last:border-0">
                    <td className="break-words py-1.5 pr-2">{cell.asset.trim() || t("common:empty.translationUnavailable")}</td>
                    <td className="break-words py-1.5 pr-2">{cell.category.trim() || t("heatmap.unknownCategory")}</td>
                    <td className="py-1.5 text-right tabular-nums">{state === "unavailable" ? t("heatmap.state.unavailable") : formatChange(cell.change1d, locale)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
