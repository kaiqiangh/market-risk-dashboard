/**
 * format.ts 格式化测试（架构 §1.9/§8.2/§8.3 + T04 format 要求）。
 * 中文 2026年8月3日 / 英文 Aug 3, 2026；中文 上涨 2.35% / 英文 Up 2.35%；
 * 中文 市值 3.2万亿美元 / 英文 Market Cap $3.2T。
 */
import { describe, expect, it } from "vitest";
import {
  formatChange,
  formatCompactNumber,
  formatDate,
  formatMoneyCompact,
  formatNumber,
  formatPercentile,
  formatPctPoints,
  formatRatio,
  formatRelativeTime,
} from "@/lib/format";

describe("formatDate", () => {
  it("formats zh-CN as 2026年8月3日", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "zh-CN")).toBe("2026年8月3日");
  });
  it("formats en as Aug 3, 2026", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "en")).toBe("Aug 3, 2026");
  });
  it("returns placeholder for invalid/missing", () => {
    expect(formatDate(null, "zh-CN")).toBe("—");
    expect(formatDate("not-a-date", "zh-CN")).toBe("—");
  });
});

describe("formatChange (涨跌文案)", () => {
  it("zh-CN up", () => {
    expect(formatChange(2.35, "zh-CN")).toBe("上涨 2.35%");
  });
  it("zh-CN down", () => {
    expect(formatChange(-1.2, "zh-CN")).toBe("下跌 1.20%");
  });
  it("en up / down", () => {
    expect(formatChange(2.35, "en")).toBe("Up 2.35%");
    expect(formatChange(-1.2, "en")).toBe("Down 1.20%");
  });
  it("returns placeholder for missing", () => {
    expect(formatChange(null, "zh-CN")).toBe("—");
  });
});

describe("formatPctPoints / formatRatio", () => {
  it("percent points with sign", () => {
    expect(formatPctPoints(2.35, "zh-CN")).toBe("+2.35%");
    expect(formatPctPoints(-1.2, "en")).toBe("-1.20%");
  });
  it("0-1 ratio", () => {
    expect(formatRatio(0.72, "zh-CN")).toBe("72%");
  });
  it("formatNumber", () => {
    expect(formatNumber(38.24, "zh-CN")).toBe("38.24");
    expect(formatNumber(null, "zh-CN")).toBe("—");
  });
});

describe("formatMoneyCompact (市值)", () => {
  it("zh-CN 3.2万亿美元", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "zh-CN")).toBe("3.2万亿美元");
  });
  it("en $3.2T", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "en")).toBe("$3.2T");
  });
});

describe("formatCompactNumber", () => {
  it("en compact", () => {
    expect(formatCompactNumber(1.23e9, "en")).toBe("1.23B");
  });
  it("zh compact", () => {
    expect(formatCompactNumber(1.23e9, "zh-CN")).toBe("12.3亿");
  });
});

describe("formatPercentile", () => {
  it("zh-CN 百分位", () => {
    expect(formatPercentile(78.4, "zh-CN")).toBe("78.4百分位");
  });
  it("en pct", () => {
    expect(formatPercentile(78.4, "en")).toBe("78.4th pct");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-08-03T11:00:00Z").getTime();
  it("en 1 hour ago", () => {
    expect(formatRelativeTime("2026-08-03T10:00:00Z", "en", now)).toBe("1 hour ago");
  });
  it("zh 1 小时前", () => {
    expect(formatRelativeTime("2026-08-03T10:00:00Z", "zh-CN", now)).toBe("1小时前");
  });
});
