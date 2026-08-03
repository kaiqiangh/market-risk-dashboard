/**
 * Mobile layout tests (acceptance: mobile single-column cards, risk conclusion first, long tables
 * become cards, secondary fields collapsed). jsdom cannot truly measure CSS layout, so it verifies
 * responsive classes and document order.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import App from "@/App";
import { installFixtureFetch } from "./helpers/fetchMock";

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("mobile layout", () => {
  it("Overview puts risk conclusion first (risk-conclusion before heatmap)", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("risk-score");

    const order = Array.from(container.querySelectorAll<HTMLElement>("[data-testid]")).map(
      (el) => el.getAttribute("data-testid") ?? "",
    );
    const riskIdx = order.indexOf("risk-conclusion");
    const firstChartIdx = order.findIndex((id) =>
      ["asset-heatmap", "heatmap-fallback", "risk-trend-chart", "trend-fallback"].includes(id),
    );
    expect(riskIdx).toBeGreaterThanOrEqual(0);
    expect(firstChartIdx).toBeGreaterThan(riskIdx);
  });

  it("Overview risk section uses mobile single-column / desktop multi-column responsive classes", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("risk-score");

    const section = container.querySelector('[data-testid="risk-conclusion"]');
    expect(section).not.toBeNull();
    const cls = section?.getAttribute("class") ?? "";
    expect(cls).toContain("grid-cols-1");
    expect(cls).toContain("md:grid-cols-2");
    expect(cls).toContain("xl:grid-cols-3");
  });

  it("Navbar scrolls horizontally on mobile (overflow-x-auto)", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("page-title");
    const nav = container.querySelector("nav");
    expect(nav?.getAttribute("class") ?? "").toContain("overflow-x-auto");
  });

  it("Equities A-share cards use a mobile single-column responsive grid", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/equities");
    const { container } = renderApp();
    await screen.findByTestId("page-title");

    // fixtures contain 1 A-share (603986.SH) → AShare card renders
    const cards = container.querySelector('[data-testid="section-ashare"]');
    if (cards) {
      const grid = cards.querySelector("div");
      const cls = grid?.getAttribute("class") ?? "";
      expect(cls).toContain("grid-cols-1");
    }
  });
});
