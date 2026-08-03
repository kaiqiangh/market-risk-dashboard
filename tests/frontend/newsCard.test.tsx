/**
 * NewsCard bilingual selection tests (issue #37).
 * Canonical bilingual (ADR-0003): title/summary are English, title_zh/summary_zh Chinese.
 * Selection: zh-CN locale prefers the _zh field, en prefers the English field; each falls
 * back to the other language when the preferred one is missing — never a blank card.
 */
import { describe, expect, it, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import i18n from "@/i18n";
import { NewsCard } from "@/components/news/NewsCard";
import type { NewsItem } from "@/schemas";

function makeItem(overrides: Partial<NewsItem> = {}): NewsItem {
  return {
    id: "item-1",
    title: "Fed raises rates by 25bp",
    title_zh: "美联储加息25个基点",
    lang: "en",
    source: "Federal Reserve",
    url: "https://example.com/news/1",
    published_at: "2026-08-03T10:00:00Z",
    categories: ["macro"],
    assets: [],
    importance: 70,
    sentiment: "neutral",
    summary: "The Fed raised its target range by 25 basis points.",
    summary_zh: "美联储将目标区间上调25个基点。",
    impact_window: null,
    ...overrides,
  };
}

async function setLocale(locale: string) {
  await i18n.changeLanguage(locale);
}

describe("NewsCard bilingual selection (canonical bilingual, ADR-0003)", () => {
  // No global locale setup: each test awaits its own setLocale so changeLanguage calls cannot
  // resolve out of order (an un-awaited beforeEach call made tests race-prone).
  afterEach(() => {
    cleanup();
  });

  it("en locale shows English title and summary", async () => {
    await setLocale("en");
    render(<NewsCard item={makeItem()} />);
    expect(screen.getByText("Fed raises rates by 25bp")).toBeInTheDocument();
    expect(screen.getByText("The Fed raised its target range by 25 basis points.")).toBeInTheDocument();
    expect(screen.queryByText("美联储加息25个基点")).not.toBeInTheDocument();
  });

  it("zh-CN locale shows Chinese title and summary", async () => {
    await setLocale("zh-CN");
    render(<NewsCard item={makeItem()} />);
    expect(screen.getByText("美联储加息25个基点")).toBeInTheDocument();
    expect(screen.getByText("美联储将目标区间上调25个基点。")).toBeInTheDocument();
    expect(screen.queryByText("Fed raises rates by 25bp")).not.toBeInTheDocument();
  });

  it("zh-CN locale falls back to English when translation is missing (untranslated item)", async () => {
    await setLocale("zh-CN");
    render(<NewsCard item={makeItem({ title_zh: null, summary_zh: null })} />);
    expect(screen.getByText("Fed raises rates by 25bp")).toBeInTheDocument();
    expect(screen.getByText("The Fed raised its target range by 25 basis points.")).toBeInTheDocument();
  });

  it("en locale falls back to Chinese when only Chinese exists (untranslated zh-source item)", async () => {
    await setLocale("en");
    render(
      <NewsCard
        item={makeItem({
          lang: "zh",
          // Pre-translation zh-source data: the canonical English side is not filled yet, so the
          // raw Chinese feed text sits in title/summary. The card degrades to it rather than blanking.
          title: "全球市场收跌",
          title_zh: null,
          summary: "美股三大指数收跌",
          summary_zh: null,
        })}
      />
    );
    // No English exists yet; the card shows the only available language instead of blanking.
    expect(screen.getByText("全球市场收跌")).toBeInTheDocument();
    expect(screen.getByText("美股三大指数收跌")).toBeInTheDocument();
  });

  it("does not render a summary block when no summary exists in any language", async () => {
    await setLocale("en");
    render(<NewsCard item={makeItem({ summary: "", summary_zh: null })} />);
    expect(screen.getByText("Fed raises rates by 25bp")).toBeInTheDocument();
    expect(screen.queryByText("The Fed raised its target range by 25 basis points.")).not.toBeInTheDocument();
  });
});
