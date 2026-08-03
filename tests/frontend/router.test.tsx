/**
 * 路由 / 语言切换 / 主题切换测试（验收 2/3/4）。
 * - 8 路由可渲染（fixtures 数据）
 * - 语言切换保持当前页面（#/zh/risk-lab → #/en/risk-lab）
 * - 刷新后语言保持（localStorage + URL 段）
 * - 深色/浅色模式切换 + localStorage 持久化
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import App from "@/App";
import { LOCALE_STORAGE_KEY } from "@/i18n";
import { THEME_STORAGE_KEY } from "@/hooks/useTheme";
import { installFixtureFetch, installFailingFetch } from "./helpers/fetchMock";

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

function setHash(hash: string): void {
  window.history.replaceState(null, "", hash);
}

beforeEach(() => {
  window.localStorage.clear();
  setHash("#/zh/overview");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("路由渲染（fixtures 数据）", () => {
  it("overview 渲染风险结论 + AI 简报", async () => {
    installFixtureFetch();
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("总览"));
    expect(await screen.findByTestId("risk-score")).toHaveTextContent("52.3");
    expect(screen.getByTestId("risk-level")).toHaveTextContent("谨慎");
    expect(screen.getByTestId("market-regime")).toHaveTextContent("周期末段");
    expect(await screen.findByTestId("ai-brief")).toBeInTheDocument();
  });

  it.each([
    ["macro", "宏观"],
    ["equities", "股票"],
    ["themes", "主题"],
    ["news", "新闻"],
    ["calendar", "日历"],
    ["risklab", "风险实验室"],
    ["status", "系统状态"],
  ])("页面 %s 可渲染（fixtures）", async (page, title) => {
    installFixtureFetch();
    setHash(`#/zh/${page}`);
    renderApp();
    expect(await screen.findByTestId("page-title")).toHaveTextContent(title);
  });

  it("非法语言段 → 重定向 /zh/overview", async () => {
    installFixtureFetch();
    setHash("#/fr/overview");
    renderApp();
    await waitFor(() => expect(window.location.hash).toContain("/zh/overview"));
  });
});

describe("JSON 读取失败 → ErrorState", () => {
  it("数据不可达时渲染 ErrorState（不崩溃）", async () => {
    installFailingFetch();
    renderApp();
    const alerts = await screen.findAllByRole("alert", {}, { timeout: 5000 });
    expect(alerts.length).toBeGreaterThan(0);
    expect(screen.getAllByText("数据加载失败").length).toBeGreaterThan(0);
  });
});

describe("语言切换（保持当前页面）", () => {
  it("risk-lab 页切换 zh→en 后仍在 risk-lab", async () => {
    installFixtureFetch();
    setHash("#/zh/risklab");
    renderApp();
    expect(await screen.findByTestId("page-title")).toHaveTextContent("风险实验室");

    fireEvent.click(screen.getByTestId("lang-switch"));

    await waitFor(() => expect(window.location.hash).toBe("#/en/risklab"));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Risk Lab"));
  });

  it("overview 页切换 en→zh 后仍在 overview", async () => {
    installFixtureFetch();
    setHash("#/en/overview");
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Overview"));

    fireEvent.click(screen.getByTestId("lang-switch"));

    await waitFor(() => expect(window.location.hash).toBe("#/zh/overview"));
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("总览"));
  });

  it("刷新后语言保持（URL 段 + localStorage）", async () => {
    installFixtureFetch();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    setHash("#/en/macro");
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Macro"));
  });
});

describe("主题切换", () => {
  it("深色默认 → 点击切换浅色 → localStorage 持久化", async () => {
    installFixtureFetch();
    renderApp();
    await screen.findByTestId("page-title");

    expect(document.documentElement.classList.contains("dark")).toBe(true);

    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
