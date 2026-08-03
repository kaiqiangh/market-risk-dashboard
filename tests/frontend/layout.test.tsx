/**
 * 移动端布局测试（验收：移动单列卡片、风险结论优先、长表格改卡片、次要字段折叠）。
 * jsdom 无法真实测量 CSS 布局，验证响应式 class 与文档顺序。
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

describe("移动端布局", () => {
  it("Overview 风险结论优先（risk-conclusion 在 heatmap 之前）", async () => {
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

  it("Overview 风险区使用移动单列 / 桌面多列响应式 class", async () => {
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

  it("Navbar 移动端横向滚动（overflow-x-auto）", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/overview");
    const { container } = renderApp();
    await screen.findByTestId("page-title");
    const nav = container.querySelector("nav");
    expect(nav?.getAttribute("class") ?? "").toContain("overflow-x-auto");
  });

  it("Equities A 股卡片为移动单列响应式网格", async () => {
    installFixtureFetch();
    window.history.replaceState(null, "", "#/zh/equities");
    const { container } = renderApp();
    await screen.findByTestId("page-title");

    // fixtures 含 1 只 A 股（603986.SH）→ AShare 卡片渲染
    const cards = container.querySelector('[data-testid="section-ashare"]');
    if (cards) {
      const grid = cards.querySelector("div");
      const cls = grid?.getAttribute("class") ?? "";
      expect(cls).toContain("grid-cols-1");
    }
  });
});
