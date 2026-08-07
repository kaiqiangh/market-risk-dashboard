/**
 * Mobile layout tests (acceptance: mobile single-column cards, risk conclusion first, long tables
 * become cards, secondary fields collapsed). jsdom cannot truly measure CSS layout, so it verifies
 * responsive classes and document order.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { cleanup, configure, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import App from "@/App";
import { installFixtureFetch } from "./helpers/fetchMock";

// CI runs all 12 test files in parallel; lazy-loaded routes + TanStack Query
// can exceed the default 1s findBy timeout under CPU contention.
configure({ asyncUtilTimeout: 5000 });

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

  it("Overview KPI strip uses mobile single-column / desktop four-column responsive classes", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("risk-score");

    const section = container.querySelector('[data-testid="risk-conclusion"]');
    expect(section).not.toBeNull();
    const cls = section?.getAttribute("class") ?? "";
    expect(cls).toContain("grid-cols-1");
    expect(cls).toContain("md:grid-cols-2");
    expect(cls).toContain("xl:grid-cols-4");
  });

  it("open chart region: trend chart renders without card chrome (spec #23)", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    renderApp();
    const chart = await screen.findByTestId("trend-fallback");
    let el: HTMLElement | null = chart;
    let wrappedInCard = false;
    while (el) {
      if (el.classList?.contains("bg-card")) {
        wrappedInCard = true;
        break;
      }
      el = el.parentElement;
    }
    expect(wrappedInCard).toBe(false);
  });

  it("Navbar keeps four direct mobile destinations and groups the rest under More", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("page-title");
    const nav = container.querySelector("nav");
    expect(nav?.getAttribute("class") ?? "").not.toContain("overflow-x-auto");
    expect(screen.getByRole("link", { name: /总览/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /宏观/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /股票/ })).toBeVisible();
    expect(screen.getByRole("link", { name: /新闻/ })).toBeVisible();
    const more = screen.getByRole("button", { name: "更多" });
    expect(more).toBeVisible();
    expect(more.className).toContain("min-h-11");
    fireEvent.click(more);
    expect(screen.getByRole("menuitem", { name: /板块/ })).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: /板块/ }));
    expect(screen.queryByRole("menu")).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: /系统状态/ }));
    const activeMore = await screen.findByRole("button", { name: /更多 \(当前\)/ });
    expect(activeMore).toHaveAttribute("aria-current", "page");
    expect(container.querySelector("nav")?.className ?? "").toContain("basis-full");
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
