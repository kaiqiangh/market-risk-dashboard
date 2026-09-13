import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import "@/i18n";
import { EvidenceLink } from "@/components/ai/EvidenceLink";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";

const { init, chart } = vi.hoisted(() => {
  const mockedChart = { dispose: vi.fn(), resize: vi.fn(), setOption: vi.fn() };
  return { chart: mockedChart, init: vi.fn(() => mockedChart) };
});

vi.mock("@/charts/echarts", () => ({ default: { init } }));

import { RiskTrendChart } from "@/charts/RiskTrendChart";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("T10 frontend hardening", () => {
  it("EvidenceLink expands an adversarial path without selector errors", () => {
    render(
      <EvidenceLink
        refs={[
          {
            dataset: "risk",
            path: 'payload[0]"\\\\bad',
            metric: "total_score",
            value: 52.3,
            updated_at: null,
          },
        ]}
      />,
    );

    expect(() => fireEvent.click(screen.getByRole("button"))).not.toThrow();
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(screen.getByRole("button"), { key: "Enter" });
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false");
  });

  it("reuses the ECharts instance when trend data changes in place", async () => {
    vi.stubGlobal("navigator", { userAgent: "Chrome" });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      {} as CanvasRenderingContext2D,
    );
    const { rerender } = render(
      <RiskTrendChart
        points={[
          { date: "2026-08-01", total_score: 48.1 },
          { date: "2026-08-02", total_score: 52.3 },
        ]}
      />,
    );
    rerender(
      <RiskTrendChart
        points={[
          { date: "2026-08-01", total_score: 49.1 },
          { date: "2026-08-02", total_score: 53.3 },
        ]}
      />,
    );

    await waitFor(() => expect(init).toHaveBeenCalledTimes(1));
    expect(chart.setOption).toHaveBeenCalledWith(expect.any(Object), { notMerge: true });
  });

  it("renders recovery UI when a lazy route throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    function BrokenPage(): never {
      throw new Error("chunk failed");
    }

    render(
      <ErrorBoundary>
        <BrokenPage />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Reload");
  });
});
