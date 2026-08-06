/**
 * English long-text layout / Chinese wrapping tests (PRD §25.2 / §8.10).
 * jsdom has no real layout engine, so rendering-level assertions are used: very long English/Chinese
 * text renders without crashing, the full text appears in the DOM, and news card titles/summaries
 * enable break-words (long-word wrapping support).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider, initReactI18next } from "react-i18next";
import i18n from "i18next";
import { NewsCard } from "@/components/news/NewsCard";
import { NewsList } from "@/components/news/NewsList";
import type { NewsItem } from "@/schemas";

const LONG_EN_TITLE =
  "SemiconductorMemorySupplyChainDisruptionSignalsMountAsInventoryCorrectionDeepensAcrossDRAMAndNANDMarketsWorldwide";
const LONG_ZH_TITLE = "半导体存储供应链中断信号持续累积，库存修正周期在DRAM与NAND全球市场中不断深化，市场参与者密切关注供需再平衡节奏";
const LONG_SUMMARY =
  "This is an extremely long English summary used to verify that long-form text wraps and does not break the card layout. ".repeat(6).trim();

function renderWithI18n(ui: React.ReactNode, lang: "zh-CN" | "en") {
  const instance = i18n.createInstance();
  instance.use(initReactI18next).init({
    lng: lang,
    fallbackLng: "zh-CN",
    resources: {
      "zh-CN": {
        news: {
          readMore: "阅读更多",
        },
      },
      en: {
        news: {
          readMore: "Read more",
        },
      },
    },
  });
  return render(<I18nextProvider i18n={instance}>{ui}</I18nextProvider>);
}

function makeItem(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    id: "item-1",
    title: "Test title",
    title_zh: null,
    lang: "en",
    source: "Test Source",
    url: "https://example.com/news/1",
    published_at: "2026-08-03T10:00:00Z",
    categories: ["macro"],
    assets: ["SPY"],
    importance: 50,
    sentiment: "neutral",
    summary: "A short summary.",
    summary_zh: null,
    impact_window: null,
    ...overrides,
  };
}

describe("English long-text layout", () => {
  it("very long English title renders without crashing and in full", () => {
    renderWithI18n(<NewsCard item={makeItem({ title: LONG_EN_TITLE })} />, "en");
    expect(screen.getByText(LONG_EN_TITLE)).toBeDefined();
  });

  it("very long English summary renders without crashing and in full", () => {
    renderWithI18n(<NewsCard item={makeItem({ title: "Title", summary: LONG_SUMMARY })} />, "en");
    expect(screen.getByText(LONG_SUMMARY)).toBeDefined();
  });

  it("news card title enables break-words (long words can wrap)", () => {
    renderWithI18n(<NewsCard item={makeItem({ title: LONG_EN_TITLE })} />, "en");
    const titleEl = screen.getByText(LONG_EN_TITLE);
    expect(titleEl.className).toContain("break-words");
  });

  it("news list renders multiple very long English items", () => {
    const items = [1, 2, 3].map((n) =>
      makeItem({ id: `item-${n}`, title: `${LONG_EN_TITLE}-${n}`, summary: LONG_SUMMARY }),
    );
    renderWithI18n(<NewsList items={items} />, "en");
    for (const item of items) {
      expect(screen.getByText(item.title)).toBeDefined();
    }
  });
});

describe("Chinese wrapping", () => {
  it("long Chinese title renders without crashing and in full", () => {
    renderWithI18n(<NewsCard item={makeItem({ title: LONG_ZH_TITLE, title_zh: LONG_ZH_TITLE })} />, "zh-CN");
    expect(screen.getByText(LONG_ZH_TITLE)).toBeDefined();
  });

  it("long Chinese summary renders without crashing and in full", () => {
    const zhSummary = "这是用于验证中文长文本在卡片内正常换行显示而不破坏布局的超长摘要文本。".repeat(6);
    renderWithI18n(<NewsCard item={makeItem({ title: "标题", summary: zhSummary })} />, "zh-CN");
    expect(screen.getByText(zhSummary)).toBeDefined();
  });

  it("Chinese UI renders an English title (no translation) without crashing", () => {
    renderWithI18n(<NewsCard item={makeItem({ title: LONG_EN_TITLE, title_zh: null })} />, "zh-CN");
    expect(screen.getByText(LONG_EN_TITLE)).toBeDefined();
  });
});
