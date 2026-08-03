import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatDate, formatNumber } from "@/lib/format";

/** jsdom/无 canvas 环境 → 走 HTML 降级（避免 zrender 动画循环崩溃）。 */
function canvasSupported(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(canvas.getContext && canvas.getContext("2d"));
  } catch {
    return false;
  }
}

/**
 * RiskTrendChart：风险趋势（history/risk/{slice}.json，ECharts 折线 + 面积）。
 * - 首屏只加载 30d 切片（架构 §1.7）。
 * - jsdom/无 canvas 环境自动降级为 HTML 表格（可测试、可访问）。
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
          axisLine: { lineStyle: { color: "rgba(148,163,184,0.5)" } },
          axisLabel: { color: "#94a3b8", fontSize: 10 },
        },
        yAxis: {
          type: "value",
          min: 0,
          max: 100,
          axisLabel: { color: "#94a3b8", fontSize: 10 },
          splitLine: { lineStyle: { color: "rgba(148,163,184,0.15)" } },
        },
        series: [
          {
            name: t("trend.score"),
            type: "line",
            smooth: true,
            showSymbol: false,
            data: scores,
            lineStyle: { color: "#38bdf8", width: 2 },
            areaStyle: { color: "rgba(56,189,248,0.12)" },
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
