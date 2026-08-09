import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { chartTheme } from "./theme";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate, formatNumber } from "@/lib/format";

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

/** One series' sparse column-oriented history (history/macro/{group}.{30d,90d}.json, #96). */
export interface MacroSeriesColumns {
  d: string[];
  v: number[];
}

/** Bundle shape: series id → {d: dates, v: values} (each series carries its own date axis —
 * mixed-frequency groups need no null padding, #84 §3). */
export type MacroBundle = Record<string, MacroSeriesColumns>;

/**
 * MacroHistoryChart: one group's 30d/90d history as a multi-series line chart
 * (ECharts LineChart, imported on demand). Sparse per-series date axes are joined onto a
 * union date axis (missing values render as gaps). No canvas → HTML fallback table.
 */
export interface MacroHistoryChartProps {
  bundle: MacroBundle;
  height?: number;
}

export function MacroHistoryChart({ bundle, height = 260 }: MacroHistoryChartProps) {
  const { t, i18n } = useTranslation("macro");
  const locale = i18n.language;
  const ref = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"echarts" | "fallback">("echarts");

  useEffect(() => {
    if (!ref.current || Object.keys(bundle).length === 0) return;
    if (!canvasSupported()) {
      setMode("fallback");
      return;
    }
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      const th = chartTheme();
      const allDates = Array.from(new Set(Object.values(bundle).flatMap((s) => s.d))).sort();
      const series = Object.entries(bundle).map(([name, cols]) => ({
        name,
        type: "line" as const,
        showSymbol: false,
        connectNulls: false,
        data: allDates.map((d) => {
          const idx = cols.d.indexOf(d);
          return idx >= 0 ? cols.v[idx] : null;
        }),
      }));
      chart.setOption({
        grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
        legend: { textStyle: { color: th.axis, fontSize: 10 }, top: 2 },
        tooltip: {
          trigger: "axis",
          formatter: (params: unknown) => {
            const list = params as Array<{ axisValue: string; seriesName: string; data: number | null }>;
            if (!Array.isArray(list) || list.length === 0) return "";
            const rows = list
              .filter((p) => p.data !== null)
              .map((p) => `${p.seriesName}: <b>${formatNumber(p.data as number, locale)}</b>`)
              .join("<br/>");
            return `${formatDate(list[0].axisValue, locale)}<br/>${rows}`;
          },
        },
        xAxis: {
          type: "category",
          data: allDates,
          axisLine: { lineStyle: { color: th.grid } },
          axisLabel: { color: th.axis, fontSize: 10 },
        },
        yAxis: {
          type: "value",
          scale: true,
          axisLabel: { color: th.axis, fontSize: 10 },
          splitLine: { lineStyle: { color: th.grid } },
        },
        series,
      });
    } catch {
      setMode("fallback");
    }
    return () => chart?.dispose();
  }, [bundle, locale]);

  if (Object.keys(bundle).length === 0) {
    return <EmptyState title={t("history.empty")} />;
  }

  if (mode === "fallback") {
    return (
      <div className="overflow-x-auto" data-testid="macro-history-fallback">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 pr-2 font-medium">{t("history.series")}</th>
              <th className="py-1.5 pr-2 font-medium">{t("history.latest")}</th>
              <th className="py-1.5 font-medium">{t("history.date")}</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(bundle).map(([name, cols]) => {
              const lastIdx = cols.v.length - 1;
              return (
                <tr key={name} className="border-b border-border/50 last:border-0">
                  <td className="py-1.5 pr-2 font-mono">{name}</td>
                  <td className="py-1.5 pr-2 tabular-nums">{lastIdx >= 0 ? formatNumber(cols.v[lastIdx], locale) : "—"}</td>
                  <td className="py-1.5 tabular-nums text-muted-foreground">{lastIdx >= 0 ? formatDate(cols.d[lastIdx], locale) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return <div ref={ref} style={{ height }} data-testid="macro-history-chart" />;
}
