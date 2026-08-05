import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { chartTheme } from "./theme";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatChange } from "@/lib/format";

/** jsdom / no-canvas environment → fall back to HTML (avoid zrender animation loop crashes). */
function canvasSupported(): boolean {
  if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) return false;
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext && canvas.getContext("2d"));
  } catch {
    return false;
  }
}

/**
 * AssetHeatmap: cross-asset heatmap (ECharts heatmap).
 * cells: asset change (%) matrix; color red = down / green = up (paired with value text, color is not the only expression).
 * Empty data → EmptyState; jsdom without canvas → HTML grid fallback.
 */
export interface HeatmapCell {
  asset: string;
  category: string;
  change1d: number | null;
}

export interface AssetHeatmapProps {
  cells: HeatmapCell[];
  height?: number;
}

export function AssetHeatmap({ cells, height = 320 }: AssetHeatmapProps) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const ref = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"echarts" | "fallback">("echarts");

  const validCells = cells.filter((c) => c.change1d !== null && c.change1d !== undefined);
  const categories = Array.from(new Set(cells.map((c) => c.category)));
  // One row per asset so cells never collapse onto the same (x, y) coordinate. The
  // previous layout pinned y = 0, so every asset in a category stacked into one cell
  // and their % labels overlapped in the centre.
  const rows = validCells.map((c) => c.asset);
  // Grow the chart with the row count so each cell keeps enough height for its label.
  const computedHeight = Math.min(560, Math.max(height, validCells.length * 26 + 64));

  useEffect(() => {
    if (!ref.current || validCells.length === 0) return;
    if (!canvasSupported()) {
      setMode("fallback");
      return;
    }
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      const th = chartTheme();
      const data = validCells.map((c, i) => [categories.indexOf(c.category), i, c.change1d as number]);
      chart.setOption({
        grid: { left: 8, right: 24, top: 24, bottom: 8, containLabel: true },
        tooltip: {
          formatter: (params: unknown) => {
            const p = params as { data: number[]; name?: string };
            const catIdx = Math.round((p.data?.[0] ?? 0) as number);
            const rowIdx = Math.round((p.data?.[1] ?? 0) as number);
            const cat = categories[catIdx] ?? "";
            const asset = rows[rowIdx] ?? "";
            const val = p.data?.[2] as number;
            return `${asset}<br/>${cat}<br/>${formatChange(val, locale)}`;
          },
        },
        xAxis: {
          type: "category",
          data: categories,
          axisLabel: { color: th.axis, fontSize: 10, interval: 0 },
        },
        yAxis: {
          type: "category",
          data: rows,
          axisLabel: { color: th.axis, fontSize: 10 },
        },
        visualMap: {
          min: -8,
          max: 8,
          calculable: true,
          orient: "vertical",
          right: 0,
          top: "center",
          textStyle: { color: th.axis, fontSize: 10 },
          inRange: {
            // Direction family (ADR-0002): muted down → neutral surface → muted up
            color: [th.dirDown, th.neutral, th.dirUp],
          },
        },
        series: [
          {
            name: t("heatmap.title"),
            type: "heatmap",
            data,
            label: {
              show: true,
              color: th.onFill,
              fontSize: 11,
              formatter: (p: unknown) => {
                const pp = p as { data: number[] };
                const val = pp.data?.[2] as number;
                return val === null || val === undefined ? "—" : `${val > 0 ? "+" : ""}${Number(val).toFixed(1)}%`;
              },
            },
            itemStyle: { borderColor: th.grid, borderWidth: 1 },
            // Glow budget: hover emphasis is a border highlight, not a shadow
            emphasis: { itemStyle: { borderColor: th.accent, borderWidth: 2 } },
          },
        ],
      });
      const onResize = () => chart?.resize();
      window.addEventListener("resize", onResize);
      return () => {
        window.removeEventListener("resize", onResize);
        chart?.dispose();
      };
    } catch {
      setMode("fallback");
      return;
    }
  }, [validCells, categories, locale, t]);

  if (cells.length === 0) {
    return <EmptyState title={t("heatmap.empty")} data-testid="chart-empty" />;
  }

  if (mode === "fallback") {
    return (
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" data-testid="heatmap-fallback">
        {validCells.map((c) => {
          const up = (c.change1d as number) >= 0;
          return (
            <div
              key={`${c.category}-${c.asset}`}
              className={`rounded-md border px-2 py-1.5 text-center ${
                up ? "border-dir-up/40 bg-dir-up/10" : "border-dir-down/40 bg-dir-down/10"
              }`}
            >
              <p className="text-[11px] text-muted-foreground">{c.asset}</p>
              <p className={`text-sm font-semibold tabular-nums ${up ? "text-dir-up" : "text-dir-down"}`}>
                {formatChange(c.change1d, locale)}
              </p>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <>
      <div ref={ref} style={{ height: computedHeight }} data-testid="asset-heatmap" className="w-full" />
      <details className="mt-2 rounded-md border border-border px-3 py-2 text-xs">
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
              {validCells.map((cell) => (
                <tr key={`${cell.category}-${cell.asset}`} className="border-b border-border/50 last:border-0">
                  <td className="break-words py-1.5 pr-2">{cell.asset}</td>
                  <td className="break-words py-1.5 pr-2">{cell.category}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatChange(cell.change1d, locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
