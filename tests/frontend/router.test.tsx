/**
 * Routing / language switch / theme switch tests (acceptance 2/3/4).
 * - 8 routes renderable (fixtures data)
 * - language switch keeps the current page (#/zh/risk-lab → #/en/risk-lab)
 * - language persists after refresh (localStorage + URL segment)
 * - dark/light mode switch + localStorage persistence
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@/i18n";
import App from "@/App";
import { LOCALE_STORAGE_KEY } from "@/i18n";
import { THEME_STORAGE_KEY } from "@/hooks/useTheme";
import { installFixtureFetch, installFailingFetch } from "./helpers/fetchMock";

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

describe("route rendering (fixtures data)", () => {
  it("overview renders risk conclusion + AI brief", async () => {
    installFixtureFetch();
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("总览"));
    expect(await screen.findByTestId("risk-score")).toHaveTextContent("52.3");
    expect(screen.getByTestId("risk-level")).toHaveTextContent("谨慎");
    expect(screen.getByTestId("market-regime")).toHaveTextContent("周期末段");
    // #121: 板块表现 lists all sector baskets (sectors + themes merged), not just the 2 headline sectors.
    const sectorPerformance = await screen.findByTestId("sector-performance");
    expect(within(sectorPerformance).getByText("半导体龙头")).toBeInTheDocument(); // sectors.semis
    expect(within(sectorPerformance).getByText("存储")).toBeInTheDocument(); // themes.memory
    expect(within(sectorPerformance).getByText("网络安全")).toBeInTheDocument(); // themes.cybersecurity
    expect(await screen.findByTestId("ai-brief")).toBeInTheDocument();
  });

  it("overview renders the validated brief on both locale routes", async () => {
    installFixtureFetch();
    renderApp();
    expect(await screen.findByTestId("ai-brief")).toBeInTheDocument();
    expect(screen.getByText("智能市场简报")).toBeInTheDocument();
    expect(screen.getAllByText("主要风险驱动").length).toBeGreaterThan(0);
    expect(screen.getByText("英文")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Top 风险驱动");
    expect(document.body.textContent).not.toContain("This indicator is a modeled estimate");
    expect(document.body.textContent).not.toContain("1M ");

    fireEvent.click(screen.getByTestId("lang-switch"));

    await waitFor(() => expect(window.location.hash).toBe("#/en/overview"));
    expect(await screen.findByTestId("ai-brief")).toBeInTheDocument();
    expect(screen.getByText("AI Market Brief")).toBeInTheDocument();
  });

  it.each([
    ["macro", "宏观"],
    ["equities", "股票"],
    ["themes", "板块"],
    ["news", "新闻"],
    ["calendar", "日历"],
    ["risklab", "风险实验室"],
    ["status", "系统状态"],
  ])("page %s renders (fixtures)", async (page, title) => {
    installFixtureFetch();
    setHash(`#/zh/${page}`);
    renderApp();
    expect(await screen.findByTestId("page-title")).toHaveTextContent(title);
  });

  it("invalid language segment → redirects to /en/overview", async () => {
    installFixtureFetch();
    setHash("#/fr/overview");
    renderApp();
    await waitFor(() => expect(window.location.hash).toContain("/en/overview"));
  });
});

describe("JSON read failure → ErrorState", () => {
  it("renders ErrorState when data is unreachable (does not crash)", async () => {
    installFailingFetch();
    renderApp();
    const alerts = await screen.findAllByRole("alert", {}, { timeout: 5000 });
    expect(alerts.length).toBeGreaterThan(0);
    expect(screen.getAllByText("数据加载失败").length).toBeGreaterThan(0);
  });
});

describe("language switch (keeps current page)", () => {
  it("stays on risk-lab when switching zh→en on the risk-lab page", async () => {
    installFixtureFetch();
    setHash("#/zh/risklab");
    renderApp();
    expect(await screen.findByTestId("page-title")).toHaveTextContent("风险实验室");

    fireEvent.click(screen.getByTestId("lang-switch"));

    await waitFor(() => expect(window.location.hash).toBe("#/en/risklab"));
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Risk Lab"));
  });

  it("stays on overview when switching en→zh on the overview page", async () => {
    installFixtureFetch();
    setHash("#/en/overview");
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Overview"));

    fireEvent.click(screen.getByTestId("lang-switch"));

    await waitFor(() => expect(window.location.hash).toBe("#/zh/overview"));
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("总览"));
  });

  it("language persists after refresh (URL segment + localStorage)", async () => {
    installFixtureFetch();
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    setHash("#/en/macro");
    renderApp();
    await screen.findByTestId("page-title");
    await waitFor(() => expect(screen.getByTestId("page-title")).toHaveTextContent("Macro"));
  });
});

describe("theme switch", () => {
  it("dark by default → three-way control switches preference → localStorage persists", async () => {
    installFixtureFetch();
    renderApp();
    await screen.findByTestId("page-title");

    expect(document.documentElement.classList.contains("dark")).toBe(true);

    fireEvent.click(screen.getByTestId("theme-option-light"));
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

    fireEvent.click(screen.getByTestId("theme-option-dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });
});
