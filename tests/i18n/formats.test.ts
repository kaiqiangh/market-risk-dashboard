/**
 * Date/number/currency format tests (PRD §25.2 / §8.9).
 * Exercises the bilingual format map: zh-CN vs en for dates, rise/fall copy, compact money, percentiles.
 * Raw data is always ISO 8601 UTC + raw numeric values + standard currency codes (architecture §8.2/§8.3).
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

describe("date format (PRD §8.9)", () => {
  it("zh-CN: 2026年8月3日", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "zh-CN")).toBe("2026年8月3日");
  });
  it("en: Aug 3, 2026", () => {
    expect(formatDate("2026-08-03T10:00:00Z", "en")).toBe("Aug 3, 2026");
  });
  it("datetime zh-CN contains date and time", () => {
    const s = formatDateTime("2026-08-03T10:00:00Z", "zh-CN");
    expect(s).toContain("2026");
    expect(s).toContain("8月3日");
  });
  it("time only", () => {
    expect(formatTime("2026-08-03T10:00:00Z", "zh-CN")).toMatch(/\d{1,2}:\d{2}/);
  });
  it("invalid/missing → placeholder", () => {
    expect(formatDate(null, "zh-CN")).toBe("—");
    expect(formatDate("bad-date", "en")).toBe("—");
  });
});

describe("number format (PRD §8.9)", () => {
  it("zh-CN thousands + decimals: 38.24", () => {
    expect(formatNumber(38.24, "zh-CN")).toBe("38.24");
  });
  it("en thousands: 1,234,567.89", () => {
    expect(formatNumber(1234567.89, "en")).toBe("1,234,567.89");
  });
  it("signed: +2.35 / -1.20", () => {
    expect(formatSignedNumber(2.35, "zh-CN")).toBe("+2.35");
    expect(formatSignedNumber(-1.2, "en")).toBe("-1.2");
  });
  it("percentage points: +2.35% / -1.20%", () => {
    expect(formatPctPoints(2.35, "zh-CN")).toBe("+2.35%");
    expect(formatPctPoints(-1.2, "en")).toBe("-1.20%");
  });
  it("0-1 ratio → percentage: 72%", () => {
    expect(formatRatio(0.72, "zh-CN")).toBe("72%");
    expect(formatRatio(0.875, "en")).toBe("87.5%");
  });
  it("rise/fall copy: 上涨/下跌/Up/Down", () => {
    expect(formatChange(2.35, "zh-CN")).toBe("上涨 2.35%");
    expect(formatChange(-1.2, "zh-CN")).toBe("下跌 1.20%");
    expect(formatChange(2.35, "en")).toBe("Up 2.35%");
    expect(formatChange(-1.2, "en")).toBe("Down 1.20%");
  });
  it("percentile: 78.4百分位 / 78.4th pct", () => {
    expect(formatPercentile(78.4, "zh-CN")).toBe("78.4百分位");
    expect(formatPercentile(78.4, "en")).toBe("78.4th pct");
  });
  it("compact numbers: 12.3亿 / 1.23B", () => {
    expect(formatCompactNumber(1.23e9, "zh-CN")).toBe("12.3亿");
    expect(formatCompactNumber(1.23e9, "en")).toBe("1.23B");
  });
  it("missing/NaN → placeholder", () => {
    expect(formatNumber(null, "zh-CN")).toBe("—");
    expect(formatNumber(Number.NaN, "en")).toBe("—");
  });
});

describe("currency format (PRD §8.9)", () => {
  it("zh-CN compact currency: 3.2万亿美元", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "zh-CN")).toBe("3.2万亿美元");
  });
  it("en compact currency: $3.2T", () => {
    expect(formatMoneyCompact(3.2e12, "USD", "en")).toBe("$3.2T");
  });
  it("zh-CN CNY: 人民币 compact", () => {
    const s = formatMoneyCompact(1.5e9, "CNY", "zh-CN");
    expect(s).toContain("人民币");
    expect(s).toContain("15");
  });
  it("full currency: $1,235 / ¥1,235", () => {
    expect(formatMoney(1234.56, "USD", "en")).toBe("$1,235");
    expect(formatMoney(1234.56, "CNY", "zh-CN")).toBe("¥1,235");
  });
  it("unit suffix: pct→%、usd→USD、bps→bp/bps", () => {
    expect(formatUnitSuffix("pct", "zh-CN")).toBe("%");
    expect(formatUnitSuffix("usd", "zh-CN")).toBe("USD");
    expect(formatUnitSuffix("bps", "zh-CN")).toBe("bp");
    expect(formatUnitSuffix("bps", "en")).toBe("bps");
  });
});

describe("raw data conventions (architecture §8.2/§8.3)", () => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const dataDir = path.resolve(__dirname, "../../public/data/latest");

  it("data file timestamps are ISO 8601 UTC (Z suffix)", () => {
    const files = readdirSync(dataDir).filter((f) => f.endsWith(".json"));
    expect(files.length).toBeGreaterThan(0);
    const isoUtc = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
    for (const f of files) {
      const data = JSON.parse(readFileSync(path.join(dataDir, f), "utf-8"));
      const ts = data.generated_at;
      if (ts !== undefined) {
        expect(isoUtc.test(ts), `${f}.generated_at should be ISO 8601 UTC: ${ts}`).toBe(true);
      }
    }
  });

  it("risk score is a raw 0-100 number (not formatted at storage)", () => {
    const riskPath = path.join(dataDir, "risk.json");
    const risk = JSON.parse(readFileSync(riskPath, "utf-8"));
    const total = risk.payload.total_score;
    expect(typeof total).toBe("number");
    expect(total).toBeGreaterThanOrEqual(0);
    expect(total).toBeLessThanOrEqual(100);
  });
});
