import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatChange } from "@/lib/format";

/** jsdom / no-canvas environment → fall back to HTML (avoid zrender animation loop crashes). */
function canvasSupported(): boolean {
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

  useEffect(() => {
    if (!ref.current || validCells.length === 0) return;
    if (!canvasSupported()) {
      setMode("fallback");
      return;
    }
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      const data = validCells.map((c) => [categories.indexOf(c.category), 0, c.change1d as number]);
      // Y axis groups by asset (one pool per category row; MVP uses category as the y axis)
      chart.setOption({
        grid: { left: 8, right: 24, top: 24, bottom: 8, containLabel: true },
        tooltip: {
          formatter: (params: unknown) => {
            const p = params as { data: number[]; name?: string };
            const idx = Math.round((p.data?.[0] ?? 0) as number);
            const cat = categories[idx] ?? "";
            const val = p.data?.[2] as number;
            return `${cat}<br/>${formatChange(val, locale)}`;
          },
        },
        xAxis: {
          type: "category",
          data: categories,
          axisLabel: { color: "#94a3b8", fontSize: 10, interval: 0 },
        },
        yAxis: {
          type: "category",
          data: [t("heatmap.axis")],
          axisLabel: { color: "#94a3b8", fontSize: 10 },
        },
        visualMap: {
          min: -8,
          max: 8,
          calculable: true,
          orient: "vertical",
          right: 0,
          top: "center",
          textStyle: { color: "#94a3b8", fontSize: 10 },
          inRange: {
            color: ["#ef4444", "#f8fafc", "#22c55e"],
          },
        },
        series: [
          {
            name: t("heatmap.title"),
            type: "heatmap",
            data,
            label: {
              show: true,
              color: "#0f172a",
              fontSize: 11,
              formatter: (p: unknown) => {
                const pp = p as { data: number[] };
                const val = pp.data?.[2] as number;
                return val === null || val === undefined ? "—" : `${val > 0 ? "+" : ""}${Number(val).toFixed(1)}%`;
              },
            },
            itemStyle: { borderColor: "rgba(15,23,42,0.6)", borderWidth: 1 },
            emphasis: { itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.3)" } },
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
                up ? "border-risk-low/40 bg-risk-low/10" : "border-risk-severe/40 bg-risk-severe/10"
              }`}
            >
              <p className="text-[11px] text-muted-foreground">{c.asset}</p>
              <p className={`text-sm font-semibold tabular-nums ${up ? "text-risk-low" : "text-risk-severe"}`}>
                {formatChange(c.change1d, locale)}
              </p>
            </div>
          );
        })}
      </div>
    );
  }

  return <div ref={ref} style={{ height }} data-testid="asset-heatmap" className="w-full" />;
}
