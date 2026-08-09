import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import echarts from "./echarts";
import { chartTheme } from "./theme";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatNumber, formatUnitSuffix } from "@/lib/format";

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
 * MacroChart: macro indicator bar chart (ECharts BarChart, imported on demand).
 * items: { label, value, unit }[]; empty data → EmptyState; no canvas → HTML fallback.
 */
export interface MacroChartItem {
  label: string;
  value: number;
  unit?: string;
}

export interface MacroChartProps {
  items: MacroChartItem[];
  height?: number;
}

export function MacroChart({ items, height = 260 }: MacroChartProps) {
  const { t, i18n } = useTranslation("macro");
  const locale = i18n.language;
  const ref = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"echarts" | "fallback">("echarts");

  useEffect(() => {
    if (!ref.current || items.length === 0) return;
    if (!canvasSupported()) {
      setMode("fallback");
      return;
    }
    let chart: echarts.ECharts | undefined;
    try {
      chart = echarts.init(ref.current);
      const th = chartTheme();
      chart.setOption({
        grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
        tooltip: {
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: (params: unknown) => {
            const list = params as Array<{ axisValue: string; data: number }>;
            if (!Array.isArray(list) || list.length === 0) return "";
            const p = list[0];
            const item = items.find((i) => i.label === p.axisValue);
            return `${p.axisValue}<br/>${formatNumber(p.data, locale)}${item?.unit ? ` ${formatUnitSuffix(item.unit, locale)}` : ""}`;
          },
        },
        xAxis: {
          type: "category",
          data: items.map((i) => i.label),
          axisLabel: { color: th.axis, fontSize: 10, interval: 0, rotate: items.length > 5 ? 30 : 0 },
        },
        yAxis: {
          type: "value",
          axisLabel: { color: th.axis, fontSize: 10 },
          splitLine: { lineStyle: { color: th.grid } },
        },
        series: [
          {
            type: "bar",
            data: items.map((i) => i.value),
            itemStyle: { color: th.accent, borderRadius: [2, 2, 0, 0] },
            barMaxWidth: 40,
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
  }, [items, locale, t]);

  if (items.length === 0) {
    return <EmptyState title={t("chart.empty")} data-testid="chart-empty" />;
  }

  if (mode === "fallback") {
    return (
      <div className="flex flex-col gap-1.5" data-testid="macro-chart-fallback">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2 text-xs">
            <span className="w-32 shrink-0 truncate text-muted-foreground">{item.label}</span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-muted">
              <div
                className="h-full rounded bg-primary/70"
                style={{ width: `${Math.min(100, Math.abs(item.value) * 8)}%` }}
              />
            </div>
            <span className="w-16 shrink-0 text-right tabular-nums text-foreground">
              {formatNumber(item.value, locale)}
              {item.unit ? ` ${formatUnitSuffix(item.unit, locale)}` : ""}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      <div ref={ref} style={{ height }} data-testid="macro-chart" className="w-full" />
      <details className="mt-2 rounded-md border border-border px-3 py-2 text-xs">
        <summary className="cursor-pointer font-medium text-muted-foreground">{t("chart.details")}</summary>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 pr-2 font-medium">{t("indicator.name")}</th>
                <th className="py-1.5 text-right font-medium">{t("indicator.unit")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.label} className="border-b border-border/50 last:border-0">
                  <td className="break-words py-1.5 pr-2">{item.label}</td>
                  <td className="py-1.5 text-right tabular-nums">
                    {formatNumber(item.value, locale)}{item.unit ? ` ${formatUnitSuffix(item.unit, locale)}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
