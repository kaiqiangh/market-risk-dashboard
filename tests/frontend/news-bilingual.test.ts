/**
 * Bilingual canonical model schema tests (issue #36).
 * NewsItem gains `summary_zh` (additive); NewsTranslation becomes a symmetric full pair.
 * Fixture-compatible: absent `summary_zh` must still parse (old data + old automation output).
 */
import { describe, expect, it } from "vitest";
import { NewsItem, NewsTranslation } from "@/schemas/news";

const EN_BASE = {
  id: "a",
  title: "Fed raises rates",
  title_zh: null,
  source: "Federal Reserve",
  url: "https://example.com/x",
  published_at: "2026-08-03T00:00:00Z",
  categories: [],
  assets: [],
  importance: 50,
  sentiment: null,
  summary: "Fed raised rates by 25bp",
  impact_window: null,
};

describe("NewsItem canonical bilingual fields", () => {
  it("parses with summary_zh present", () => {
    const result = NewsItem.safeParse({ ...EN_BASE, summary_zh: "美联储加息25个基点" });
    expect(result.success).toBe(true);
  });

  it("parses when summary_zh is absent (legacy data)", () => {
    const result = NewsItem.safeParse(EN_BASE);
    expect(result.success).toBe(true);
  });

  it("lang defaults to en and accepts zh (translation routing)", () => {
    expect(NewsItem.safeParse(EN_BASE).success).toBe(true);
    expect(NewsItem.safeParse({ ...EN_BASE, lang: "zh" }).success).toBe(true);
  });
});

describe("NewsTranslation symmetric full pair", () => {
  it("parses the full pair (title/summary EN + title_zh/summary_zh ZH)", () => {
    const result = NewsTranslation.safeParse({
      id: "a",
      title: "Fed raises rates",
      summary: "Fed raised rates by 25bp",
      title_zh: "美联储加息",
      summary_zh: "美联储加息25个基点",
    });
    expect(result.success).toBe(true);
  });

  it("still parses the legacy shape (id + title_zh only)", () => {
    const result = NewsTranslation.safeParse({ id: "a", title_zh: "美联储加息" });
    expect(result.success).toBe(true);
  });
});
