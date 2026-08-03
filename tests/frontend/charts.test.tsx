/**
 * 图表空态测试（架构 §8.8 缺失渲染 EmptyState）+ jsdom 降级渲染。
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@/i18n";
import { RiskTrendChart } from "@/charts/RiskTrendChart";
import { AssetHeatmap } from "@/charts/AssetHeatmap";
import { MacroChart } from "@/charts/MacroChart";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RiskTrendChart 空态", () => {
  it("points=[] → EmptyState（chart-empty）", () => {
    render(<RiskTrendChart points={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("points 非空 → 渲染图表或 HTML 降级（jsdom 无 canvas）", () => {
    render(
      <RiskTrendChart
        points={[
          { date: "2026-08-01", total_score: 48.1 },
          { date: "2026-08-02", total_score: 52.3 },
        ]}
      />,
    );
    const chart = document.querySelector('[data-testid="risk-trend-chart"], [data-testid="trend-fallback"]');
    expect(chart).not.toBeNull();
  });
});

describe("AssetHeatmap 空态", () => {
  it("cells=[] → EmptyState", () => {
    render(<AssetHeatmap cells={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("cells 非空 → 渲染图表或 HTML 降级", () => {
    render(
      <AssetHeatmap
        cells={[
          { asset: "NVDA", category: "美股", change1d: -2.1 },
          { asset: "BTC", category: "加密", change1d: -0.8 },
        ]}
      />,
    );
    const chart = document.querySelector('[data-testid="asset-heatmap"], [data-testid="heatmap-fallback"]');
    expect(chart).not.toBeNull();
  });
});

describe("MacroChart 空态", () => {
  it("items=[] → EmptyState", () => {
    render(<MacroChart items={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("items 非空 → 渲染图表或 HTML 降级", () => {
    render(
      <MacroChart
        items={[
          { label: "10Y Yield", value: 4.68, unit: "%" },
          { label: "VIX", value: 15.99 },
        ]}
      />,
    );
    const chart = document.querySelector('[data-testid="macro-chart"], [data-testid="macro-chart-fallback"]');
    expect(chart).not.toBeNull();
  });
});
