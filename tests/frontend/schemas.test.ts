/**
 * Zod 契约测试（T02 验收：同一 fixture 同时通过 Pydantic 与 Zod 校验）。
 * fixture 与 tests/fixtures/*.json 完全一致（Python 测试复用同一批文件）。
 */
import { describe, expect, it } from "vitest";
import macroFixture from "../fixtures/macro.json";
import equitiesFixture from "../fixtures/equities.json";
import sectorsFixture from "../fixtures/sectors.json";
import cryptoFixture from "../fixtures/crypto.json";
import newsFixture from "../fixtures/news.json";
import calendarFixture from "../fixtures/calendar.json";
import riskFixture from "../fixtures/risk.json";
import factsFixture from "../fixtures/facts.json";
import analysisZhFixture from "../fixtures/analysis.zh-CN.json";
import analysisEnFixture from "../fixtures/analysis.en.json";

import { AnalysisDataset } from "@/schemas/analysis";
import { CalendarEnvelope } from "@/schemas/calendar";
import { CryptoEnvelope } from "@/schemas/crypto";
import { EquitiesEnvelope } from "@/schemas/equities";
import { FactLayer } from "@/schemas/factlayer";
import { MacroEnvelope } from "@/schemas/macro";
import { NewsEnvelope } from "@/schemas/news";
import { RiskEnvelope } from "@/schemas/risk";
import { SectorsEnvelope } from "@/schemas/sectors";
import { DatasetClient } from "@/lib/api";
import { badgeFor, evaluateFreshness } from "@/lib/freshness";

const ENVELOPE_CASES: Array<[string, unknown, { safeParse: (v: unknown) => { success: boolean } }]> = [
  ["macro", macroFixture, MacroEnvelope],
  ["equities", equitiesFixture, EquitiesEnvelope],
  ["sectors", sectorsFixture, SectorsEnvelope],
  ["crypto", cryptoFixture, CryptoEnvelope],
  ["news", newsFixture, NewsEnvelope],
  ["calendar", calendarFixture, CalendarEnvelope],
  ["risk", riskFixture, RiskEnvelope],
];

describe("Zod contract: fixtures pass", () => {
  it.each(ENVELOPE_CASES)("%s envelope parses", (_key, fixture, schema) => {
    const result = schema.safeParse(fixture);
    expect(result.success).toBe(true);
  });

  it("facts.json parses as FactLayer", () => {
    expect(FactLayer.safeParse(factsFixture).success).toBe(true);
  });

  it("analysis.zh-CN.json / analysis.en.json parse as AnalysisDataset", () => {
    expect(AnalysisDataset.safeParse(analysisZhFixture).success).toBe(true);
    expect(AnalysisDataset.safeParse(analysisEnFixture).success).toBe(true);
  });
});

describe("Zod contract: hard constraints", () => {
  it("rejects NaN payload value", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.payload.rates[0].value = NaN;
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);
  });

  it("rejects Infinity payload value", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.payload.rates[0].value = Infinity;
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);
  });

  it("rejects extra fields (strict)", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.extra_key = "nope";
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);

    const bad2 = structuredClone(macroFixture) as Record<string, any>;
    bad2.payload.rates[0].sneaky = 1;
    expect(MacroEnvelope.safeParse(bad2).success).toBe(false);
  });

  it("rejects bad enum", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.freshness_status = "not_a_status";
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);
  });

  it("rejects bad datetime", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.generated_at = "2026-08-03 10:00:00";
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);
  });

  it("rejects out-of-range values", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.data_quality = 1.5;
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);

    const badRisk = structuredClone(riskFixture) as Record<string, any>;
    badRisk.payload.total_score = 120;
    expect(RiskEnvelope.safeParse(badRisk).success).toBe(false);
  });
});

describe("DatasetClient path rules (架构 §3.6)", () => {
  const client = new DatasetClient("/market-risk-dashboard/");

  it("latest dataset", () => {
    expect(client.pathFor("macro")).toBe("/market-risk-dashboard/data/latest/macro.json");
  });

  it("analysis with lang", () => {
    expect(client.pathFor("analysis", { lang: "zh-CN" })).toBe(
      "/market-risk-dashboard/data/latest/analysis.zh-CN.json",
    );
    expect(client.pathFor("analysis", { lang: "en" })).toBe(
      "/market-risk-dashboard/data/latest/analysis.en.json",
    );
  });

  it("history with slice", () => {
    expect(client.pathFor("risk", { slice: "30d" })).toBe(
      "/market-risk-dashboard/data/history/risk/30d.json",
    );
    expect(client.pathFor("market", { slice: "90d" })).toBe(
      "/market-risk-dashboard/data/history/market/90d.json",
    );
  });

  it("metadata", () => {
    expect(client.pathFor("sources")).toBe("/market-risk-dashboard/data/metadata/sources.json");
    expect(client.pathFor("freshness")).toBe("/market-risk-dashboard/data/metadata/freshness.json");
  });
});

describe("freshness five-state semantics (架构 §8.5)", () => {
  const intervalMs = 60 * 60 * 1000; // 1h
  const now = new Date("2026-08-03T12:00:00Z").getTime();

  it("evaluates time-based states", () => {
    expect(evaluateFreshness(null, intervalMs, now)).toBe("missing");
    expect(evaluateFreshness("2026-08-03T11:30:00Z", intervalMs, now)).toBe("fresh"); // 30min
    expect(evaluateFreshness("2026-08-03T10:00:00Z", intervalMs, now)).toBe("delayed"); // 2h
    expect(evaluateFreshness("2026-08-03T08:00:00Z", intervalMs, now)).toBe("stale"); // 4h
  });

  it("maps status to UI badge", () => {
    expect(badgeFor("fresh").tone).toBe("success");
    expect(badgeFor("stale").prominent).toBe(true);
    expect(badgeFor("missing").labelKey).toBe("status.missing");
    expect(badgeFor("degraded").labelKey).toBe("status.degraded");
  });
});
