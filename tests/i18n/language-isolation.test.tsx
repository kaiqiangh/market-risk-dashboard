import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import i18n from "@/i18n";
import { AssetHeatmap } from "@/charts/AssetHeatmap";
import { RiskDimensionBreakdown } from "@/components/risk/RiskDimensionBreakdown";
import ThemesPage from "@/pages/ThemesPage";
import type { RiskModelResult } from "@/schemas";
import riskFixture from "../fixtures/risk.json";
import { installFixtureFetch } from "../frontend/helpers/fetchMock";
import {
  displayEventTitle,
  displayNewsSource,
  displayProvider,
  displayReasonDetail,
  isDisplayTextSafe,
  safeDisplayText,
} from "@/lib/displayLanguage";

afterEach(() => {
  cleanup();
});

describe("display-language policy", () => {
  it("localizes provider and source identifiers, including market", () => {
    expect(displayProvider("yfinance", "zh-CN")).toBe("雅虎财经");
    expect(displayProvider("yfinance", "en")).toBe("Yahoo Finance");
    expect(displayProvider(undefined, "zh-CN")).toBe("未知数据源");
    expect(displayNewsSource("eastmoney", "zh-CN")).toBe("市场新闻源");
    expect(displayNewsSource("Federal Reserve", "en")).toBe("Federal Reserve news");
    expect(displayNewsSource("华尔街见闻", "zh-CN")).toBe("市场新闻源");
    expect(displayReasonDetail("yfinance: HTTP 429 rate limited", "zh-CN")).toBe("数据源请求受限");
    expect(displayReasonDetail("akshare: RemoteDisconnected", "en")).toBe("Provider connection interrupted");
  });

  it("does not fall back to another language for event titles", () => {
    expect(displayEventTitle("Consumer Price Index", "zh-CN")).toBe("消费者价格指数");
    expect(displayEventTitle("Unknown English event", "zh-CN")).toBe("经济事件");
    expect(displayEventTitle("中文事件", "en")).toBe("Calendar event");
  });

  it("fails closed for generated prose that crosses locale boundaries", () => {
    expect(safeDisplayText("市场状态处于 goldilocks caution", "zh-CN")).toBe("暂无本语言翻译");
    expect(safeDisplayText("当前市场状态良好", "en")).toBe("Translation unavailable");
    expect(safeDisplayText("NVDA 上涨 2.3%", "zh-CN")).toBe("NVDA 上涨 2.3%");
    expect(safeDisplayText("Risk score: 43.1", "en")).toBe("Risk score: 43.1");
  });

  it.each(["zh-CN", "en"] as const)("keeps rendered risk, heatmap, and themes surfaces in %s", async (locale) => {
    await i18n.changeLanguage(locale);
    installFixtureFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    render(
      <QueryClientProvider client={client}>
        <AssetHeatmap cells={[{ asset: "NVDA", category: locale === "zh-CN" ? "板块" : "Equities", change1d: 1.2 }]} />
        <RiskDimensionBreakdown result={riskFixture.payload as unknown as RiskModelResult} />
        <ThemesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("theme-card-memory")).toBeInTheDocument();
    expect(screen.getAllByTestId("risk-dimension").length).toBeGreaterThan(0);
    expect(screen.getByTestId("asset-heatmap")).toBeInTheDocument();
    const renderedText = Array.from(document.body.querySelectorAll("*"))
      .filter((element) => element.children.length === 0)
      .map((element) => element.textContent ?? "")
      .filter(Boolean);
    expect(renderedText.every((text) => isDisplayTextSafe(text, locale)), renderedText.join("|")).toBe(true);
  });
});
