/**
 * 日期/数字/货币格式测试（PRD §25.2 / §8.9）。
 * 中文：2026年8月3日、上涨 2.35%、市值 3.2万亿美元
 * 英文：Aug 3, 2026、Up 2.35%、Market Cap $3.2T
 * 原始数据一律 ISO 8601 UTC + 原始数值 + 标准货币代码（架构 §8.2/§8.3）。
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  formatChange,
  formatCompactNumber,
  formatDate,
  formatDateTime,
  formatMoney,
  formatMoneyCompact,
  formatNumber,
  formatPercentile,
  formatPctPoints,
  formatRatio,
  formatSignedNumber,
  formatTime,
  formatUnitSuffix,
} from "@/lib/format";

describe("日期格式（PRD §8.9）", () => {
  it("中文：2026年8月3日", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "zh-CN")).toBe("2026年8月3日");
  });
  it("英文：Aug 3, 2026", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "en")).toBe("Aug 3, 2026");
  });
  it("日期时间中文含日期与时间", () => {
    const s = formatDateTime("2026-08-03T10:00:00Z", "zh-CN");
    expect(s).toContain("2026");
    expect(s).toContain("8月3日");
  });
  it("仅时间", () => {
    expect(formatTime("2026-08-03T10:00:00Z", "zh-CN")).toMatch(/\d{1,2}:\d{2}/);
  });
  it("非法/缺失 → 占位符", () => {
    expect(formatDate(null, "zh-CN")).toBe("—");
    expect(formatDate("bad-date", "en")).toBe("—");
  });
});

describe("数字格式（PRD §8.9）", () => {
  it("中文千分位 + 小数：38.24", () => {
    expect(formatNumber(38.24, "zh-CN")).toBe("38.24");
  });
  it("英文千分位：1,234,567.89", () => {
    expect(formatNumber(1234567.89, "en")).toBe("1,234,567.89");
  });
  it("带符号：+2.35 / -1.20", () => {
    expect(formatSignedNumber(2.35, "zh-CN")).toBe("+2.35");
    expect(formatSignedNumber(-1.2, "en")).toBe("-1.2");
  });
  it("百分点：+2.35% / -1.20%", () => {
    expect(formatPctPoints(2.35, "zh-CN")).toBe("+2.35%");
    expect(formatPctPoints(-1.2, "en")).toBe("-1.20%");
  });
  it("0-1 比例 → 百分数：72%", () => {
    expect(formatRatio(0.72, "zh-CN")).toBe("72%");
    expect(formatRatio(0.875, "en")).toBe("87.5%");
  });
  it("涨跌文案：上涨/下跌/Up/Down", () => {
    expect(formatChange(2.35, "zh-CN")).toBe("上涨 2.35%");
    expect(formatChange(-1.2, "zh-CN")).toBe("下跌 1.20%");
    expect(formatChange(2.35, "en")).toBe("Up 2.35%");
    expect(formatChange(-1.2, "en")).toBe("Down 1.20%");
  });
  it("百分位：78.4百分位 / 78.4th pct", () => {
    expect(formatPercentile(78.4, "zh-CN")).toBe("78.4百分位");
    expect(formatPercentile(78.4, "en")).toBe("78.4th pct");
  });
  it("紧凑数字：12.3亿 / 1.23B", () => {
    expect(formatCompactNumber(1.23e9, "zh-CN")).toBe("12.3亿");
    expect(formatCompactNumber(1.23e9, "en")).toBe("1.23B");
  });
  it("缺失/NaN → 占位符", () => {
    expect(formatNumber(null, "zh-CN")).toBe("—");
    expect(formatNumber(Number.NaN, "en")).toBe("—");
  });
});

describe("货币格式（PRD §8.9）", () => {
  it("中文紧凑货币：3.2万亿美元", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "zh-CN")).toBe("3.2万亿美元");
  });
  it("英文紧凑货币：$3.2T", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "en")).toBe("$3.2T");
  });
  it("中文人民币：人民币紧凑", () => {
    const s = formatMoneyCompact(1.5e9, "CNY", "zh-CN");
    expect(s).toContain("人民币");
    expect(s).toContain("15");
  });
  it("全量货币：$1,235 / ¥1,235", () => {
    expect(formatMoney(1234.56, "USD", "en")).toBe("$1,235");
    expect(formatMoney(1234.56, "CNY", "zh-CN")).toBe("¥1,235");
  });
  it("单位后缀：pct→%、usd→USD、bps→bp/bps", () => {
    expect(formatUnitSuffix("pct", "zh-CN")).toBe("%");
    expect(formatUnitSuffix("usd", "zh-CN")).toBe("USD");
    expect(formatUnitSuffix("bps", "zh-CN")).toBe("bp");
    expect(formatUnitSuffix("bps", "en")).toBe("bps");
  });
});

describe("原始数据约定（架构 §8.2/§8.3）", () => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const dataDir = path.resolve(__dirname, "../../public/data/latest");

  it("数据文件时间戳为 ISO 8601 UTC（Z 后缀）", () => {
    const files = readdirSync(dataDir).filter((f) => f.endsWith(".json"));
    expect(files.length).toBeGreaterThan(0);
    const isoUtc = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
    for (const f of files) {
      const data = JSON.parse(readFileSync(path.join(dataDir, f), "utf-8"));
      const ts = data.generated_at;
      if (ts !== undefined) {
        expect(isoUtc.test(ts), `${f}.generated_at 应为 ISO 8601 UTC: ${ts}`).toBe(true);
      }
    }
  });

  it("风险分数为 0-100 原始数值（不格式化存储）", () => {
    const riskPath = path.join(dataDir, "risk.json");
    const risk = JSON.parse(readFileSync(riskPath, "utf-8"));
    const total = risk.payload.total_score;
    expect(typeof total).toBe("number");
    expect(total).toBeGreaterThanOrEqual(0);
    expect(total).toBeLessThanOrEqual(100);
  });
});
