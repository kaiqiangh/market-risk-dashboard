import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { chartTheme } from "./theme";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate, formatNumber } from "@/lib/format";

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
 * RiskTrendChart: risk trend (history/risk/{slice}.json, ECharts line + area).
 * - Initial view only loads the 30d slice (architecture §1.7).
 * - Automatically falls back to an HTML table in jsdom / no-canvas environments (testable, accessible).
 */
export interface RiskTrendPointInput {
  date: string;
  total_score: number;
  risk_level?: string;
  confidence?: number;
}

export interface RiskTrendChartProps {
  points: RiskTrendPointInput[];
  height?: number;
}

export function RiskTrendChart({ points, height = 260 }: RiskTrendChartProps) {
  const { t, i18n } = useTranslation("dashboard");
  const locale = i18n.language;
  const ref = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"echarts" | "fallback">("echarts");

  useEffect(() => {
    if (!ref.current || points.length === 0) return;
    if (!canvasSupported()) {
      setMode("fallback");
      return;
    }
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      const th = chartTheme();
      const dates = points.map((p) => p.date);
      const scores = points.map((p) => Number(p.total_score.toFixed(2)));
      chart.setOption({
        grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
        tooltip: {
          trigger: "axis",
          formatter: (params: unknown) => {
            const list = params as Array<{ axisValue: string; data: number }>;
            if (!Array.isArray(list) || list.length === 0) return "";
            const p = list[0];
            return `${formatDate(p.axisValue, locale)}<br/>${t("trend.score")}: <b>${formatNumber(p.data, locale)}</b>`;
          },
        },
        xAxis: {
          type: "category",
          data: dates,
          axisLine: { lineStyle: { color: th.grid } },
          axisLabel: { color: th.axis, fontSize: 10 },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: th.axis, fontSize: 10 },
          splitLine: { lineStyle: { color: th.grid } },
        },
        series: [
          {
            name: t("trend.score"),
            type: "line",
            smooth: true,
            showSymbol: false,
            data: scores,
            lineStyle: { color: th.accent, width: 1.5 },
            areaStyle: { color: th.accentSoft },
            // Risk thresholds in risk tones (the only saturated marks on the chart)
            markLine: {
              silent: true,
              symbol: "none",
              label: { color: th.axis, fontSize: 10 },
              data: [
                { yAxis: 70, lineStyle: { color: th.riskSevere, type: "dashed", width: 1 } },
                { yAxis: 50, lineStyle: { color: th.riskCaution, type: "dashed", width: 1 } },
              ],
            },
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
  }, [points, locale, t]);

  if (points.length === 0) {
    return <EmptyState title={t("trend.empty")} message={t("trend.emptyHint")} data-testid="chart-empty" />;
  }

  if (mode === "fallback") {
    return (
      <div className="overflow-x-auto rounded-md border border-border" data-testid="trend-fallback">
        <table className="w-full min-w-[420px] text-left text-xs">
          <thead>
            <tr className="border-b border-border text-[10px] uppercase tracking-wide text-muted-foreground">
              <th className="px-2 py-1.5 font-medium">{t("trend.date")}</th>
              <th className="px-2 py-1.5 text-right font-medium">{t("trend.score")}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.date} className="border-b border-border/50 last:border-0">
                <td className="px-2 py-1.5">{formatDate(p.date, locale)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">{formatNumber(p.total_score, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <div ref={ref} style={{ height }} data-testid="risk-trend-chart" className="w-full" />;
}
