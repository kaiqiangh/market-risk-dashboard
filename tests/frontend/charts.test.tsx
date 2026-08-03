/**
 * Chart empty-state tests (architecture §8.8 missing → EmptyState) + jsdom degraded rendering.
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

describe("RiskTrendChart empty state", () => {
  it("points=[] → EmptyState (chart-empty)", () => {
    render(<RiskTrendChart points={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("non-empty points → renders chart or HTML fallback (jsdom has no canvas)", () => {
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

describe("AssetHeatmap empty state", () => {
  it("cells=[] → EmptyState", () => {
    render(<AssetHeatmap cells={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("non-empty cells → renders chart or HTML fallback", () => {
    render(
      <AssetHeatmap
        cells={[
          { asset: "NVDA", category: "equity", change1d: -2.1 },
          { asset: "BTC", category: "crypto", change1d: -0.8 },
        ]}
      />,
    );
    const chart = document.querySelector('[data-testid="asset-heatmap"], [data-testid="heatmap-fallback"]');
    expect(chart).not.toBeNull();
  });
});

describe("MacroChart empty state", () => {
  it("items=[] → EmptyState", () => {
    render(<MacroChart items={[]} />);
    expect(screen.getByTestId("chart-empty")).toBeInTheDocument();
  });

  it("non-empty items → renders chart or HTML fallback", () => {
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
