/**
 * Zod contract tests (T02 acceptance + #73 cross-language backstop, rewired by #101).
 *
 * Since #73 the static fixture bundle is gone: the only committed documents are the three
 * hand-written GOLDENS at tests/fixtures/ (risk.json, analysis.zh-CN.json, facts.json), which
 * both this file and the Python suite read. The remaining datasets are tested here with
 * hand-written inline documents, independent of both the Python factory and the goldens.
 *
 * Since #101 the Zod side is GENERATED from the Pydantic models (src/schemas/generated/) and is
 * `.passthrough()`, not `.strict()`. The asymmetry is deliberate: the pipeline forbids extra
 * fields on the way out (extra="forbid"), the frontend tolerates them on the way in so that
 * shipping a new pipeline field cannot blank a page mid-deploy. Tolerating silently is the
 * failure mode that invites, so the backstop moved from "parse must fail" to "parse must
 * succeed AND collectUnknownFields must name the stray key". Both halves are asserted below —
 * a drift that neither rejects nor reports is the only outcome this file still calls a bug.
 */
import { describe, expect, it, vi } from "vitest";
import type { z } from "zod";
import riskFixture from "../fixtures/risk.json";
import factsFixture from "../fixtures/facts.json";
import analysisZhFixture from "../fixtures/analysis.zh-CN.json";

import {
  AnalysisDataset,
  CalendarEnvelope,
  CryptoEnvelope,
  DashboardEnvelope,
  EquitiesEnvelope,
  FactLayer,
  MacroEnvelope,
  NewsEnvelope,
  RiskEnvelope,
  SectorsEnvelope,
} from "@/schemas";
import { collectUnknownFields } from "@/lib/unknownFields";
import { DatasetClient } from "@/lib/api";
import {
  EXPECTED_INTERVALS_MIN,
  EXPECTED_INTERVALS_MS,
  badgeFor,
  effectiveStatus,
  evaluateFreshness,
  staleTimeFor,
} from "@/lib/freshness";

// -------------------------------------------------------------------------------------
// Hand-written inline documents for the datasets without goldens (#73) live in
// ./helpers/fixtureData.ts (shared with the fetch mock). They are frozen on purpose:
// independent of the Python factory, and valid against the mirrors.
// -------------------------------------------------------------------------------------
import {
  analysisEnFixture,
  calendarFixture,
  cryptoFixture,
  dashboardFixture,
  equitiesFixture,
  macroFixture,
  newsFixture,
  sectorsFixture,
} from "./helpers/fixtureData";
// -------------------------------------------------------------------------------------

const ENVELOPE_CASES: Array<[string, unknown, z.ZodTypeAny]> = [
  ["macro", macroFixture, MacroEnvelope],
  ["equities", equitiesFixture, EquitiesEnvelope],
  ["sectors", sectorsFixture, SectorsEnvelope],
  ["crypto", cryptoFixture, CryptoEnvelope],
  ["news", newsFixture, NewsEnvelope],
  ["calendar", calendarFixture, CalendarEnvelope],
  ["risk", riskFixture, RiskEnvelope],
  ["dashboard", dashboardFixture, DashboardEnvelope],
];

const GOLDEN_CASES: Array<[string, unknown, z.ZodTypeAny]> = [
  ["risk", riskFixture, RiskEnvelope],
  ["facts", factsFixture, FactLayer],
  ["analysis.zh-CN", analysisZhFixture, AnalysisDataset],
];

describe("Zod contract: documents pass", () => {
  it.each(ENVELOPE_CASES)("%s envelope parses", (_key, fixture, schema) => {
    const result = schema.safeParse(fixture);
    expect(result.success).toBe(true);
  });

  it.each(ENVELOPE_CASES)("%s envelope carries no undeclared fields", (_key, fixture, schema) => {
    // Passthrough means a fixture can drift past safeParse. The honest fixtures must stay
    // honest, or the generated contracts have fallen behind the pipeline.
    expect(collectUnknownFields(schema, fixture)).toEqual([]);
  });

  it("facts.json parses as FactLayer", () => {
    expect(FactLayer.safeParse(factsFixture).success).toBe(true);
  });

  it("analysis.zh-CN.json / analysis.en.json parse as AnalysisDataset", () => {
    expect(AnalysisDataset.safeParse(analysisZhFixture).success).toBe(true);
    expect(AnalysisDataset.safeParse(analysisEnFixture).success).toBe(true);
  });
});

describe("Zod contract: a golden that lies is reported (cross-language backstop, #73/#101)", () => {
  it.each(GOLDEN_CASES)("%s golden accepts but reports an unknown key", (_key, fixture, schema) => {
    const bad = structuredClone(fixture) as Record<string, any>;
    bad.sneaky_extra = 1;
    // Accepted — a new field must never blank the page…
    expect(schema.safeParse(bad).success).toBe(true);
    // …but never silently. The Python suite (extra="forbid") is what rejects it at the source.
    expect(collectUnknownFields(schema, bad)).toContain("sneaky_extra");
  });

  it("reports a stray field nested inside a payload row, collapsing the array index", () => {
    const bad = structuredClone(riskFixture) as Record<string, any>;
    bad.payload.top_drivers[0].sneaky = 1;
    expect(RiskEnvelope.safeParse(bad).success).toBe(true);
    expect(collectUnknownFields(RiskEnvelope, bad)).toContain("payload.top_drivers[].sneaky");
  });
});

describe("Zod contract: provenance is required (#65)", () => {
  it("rejects an envelope without provenance", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    delete bad.provenance;
    expect(MacroEnvelope.safeParse(bad).success).toBe(false);
  });

  it("accepts but reports an unknown provenance key", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    (bad.provenance as Record<string, unknown>).cache_replay = true;
    expect(MacroEnvelope.safeParse(bad).success).toBe(true);
    expect(collectUnknownFields(MacroEnvelope, bad)).toContain("provenance.cache_replay");
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

  it("tolerates extra fields but names them (passthrough, #101)", () => {
    const bad = structuredClone(macroFixture) as Record<string, any>;
    bad.extra_key = "nope";
    expect(MacroEnvelope.safeParse(bad).success).toBe(true);
    expect(collectUnknownFields(MacroEnvelope, bad)).toEqual(["extra_key"]);

    const bad2 = structuredClone(macroFixture) as Record<string, any>;
    bad2.payload.rates[0].sneaky = 1;
    expect(MacroEnvelope.safeParse(bad2).success).toBe(true);
    expect(collectUnknownFields(MacroEnvelope, bad2)).toEqual(["payload.rates[].sneaky"]);
  });

  it("keeps extra fields in the parsed output rather than stripping them", () => {
    const extended = structuredClone(macroFixture) as Record<string, any>;
    extended.payload.rates[0].change_5d = 0.25;
    const parsed = MacroEnvelope.parse(extended) as Record<string, any>;
    expect(parsed.payload.rates[0].change_5d).toBe(0.25);
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

  it("rejects a risk envelope without breadth counts (#69)", () => {
    const bad = structuredClone(riskFixture) as Record<string, any>;
    delete bad.payload.breadth;
    expect(RiskEnvelope.safeParse(bad).success).toBe(false);
  });

  it("rejects a risk envelope without per-driver discount disclosure (#69)", () => {
    const bad = structuredClone(riskFixture) as Record<string, any>;
    delete bad.payload.top_drivers[0].is_proxy;
    expect(RiskEnvelope.safeParse(bad).success).toBe(false);
  });
});

describe("DatasetClient path rules (architecture §3.6)", () => {
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

describe("freshness six-state semantics (architecture §8.5, extended by #101)", () => {
  const intervalMs = 60 * 60 * 1000; // 1h
  const now = new Date("2026-08-03T12:00:00Z").getTime();

  it("evaluates time-based states", () => {
    expect(evaluateFreshness(null, intervalMs, now)).toBe("missing");
    expect(evaluateFreshness("2026-08-03T11:30:00Z", intervalMs, now)).toBe("fresh"); // 30min
    expect(evaluateFreshness("2026-08-03T10:00:00Z", intervalMs, now)).toBe("delayed"); // 2h
    expect(evaluateFreshness("2026-08-03T08:00:00Z", intervalMs, now)).toBe("stale"); // 4h
  });

  it("maps status to UI badge, including empty", () => {
    expect(badgeFor("fresh").tone).toBe("success");
    expect(badgeFor("stale").prominent).toBe(true);
    expect(badgeFor("missing").labelKey).toBe("status.missing");
    expect(badgeFor("degraded").labelKey).toBe("status.degraded");
    // `empty` is "we asked, the source had nothing" — a fact, not an alarm.
    expect(badgeFor("empty").labelKey).toBe("status.empty");
    expect(badgeFor("empty").prominent).toBe(false);
  });

  it("effectiveStatus keys the interval on the dataset, not a hardcoded group (#101)", () => {
    // calendar publishes daily (1440min, stale past 72h); equities every 8h (stale past 24h).
    // One timestamp, 30h old, must read differently for the two — that is the whole bug #101
    // fixes, because the old code judged every dataset against the "market" interval.
    const thirtyHoursAgo = "2026-08-02T06:00:00Z";
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-03T12:00:00Z"));
    try {
      expect(effectiveStatus("fresh", thirtyHoursAgo, "calendar")).toBe("fresh");
      expect(effectiveStatus("fresh", thirtyHoursAgo, "equities")).toBe("stale");
    } finally {
      vi.useRealTimers();
    }
  });

  it("effectiveStatus never downgrades a terminal status reported by the pipeline", () => {
    for (const terminal of ["degraded", "missing", "empty"] as const) {
      expect(effectiveStatus(terminal, "2026-08-03T11:59:00Z", "equities")).toBe(terminal);
    }
  });
});

describe("staleTime by dataset freshness semantics (Fix P2-10)", () => {
  it("distinguishes market vs macro/calendar instead of uniform 60s", () => {
    expect(staleTimeFor("market")).toBe(5 * 60_000);
    expect(staleTimeFor("risk")).toBe(5 * 60_000);
    expect(staleTimeFor("news")).toBe(5 * 60_000);
    expect(staleTimeFor("macro")).toBe(10 * 60_000);
    expect(staleTimeFor("calendar")).toBe(15 * 60_000);
    expect(staleTimeFor("unknown-key")).toBe(60_000); // fallback default
  });

  it("expected intervals include risk/dashboard and align with sources.yaml", () => {
    expect(EXPECTED_INTERVALS_MIN.market).toBe(480);
    expect(EXPECTED_INTERVALS_MIN.macro).toBe(240);
    expect(EXPECTED_INTERVALS_MIN.calendar).toBe(1440);
    expect(EXPECTED_INTERVALS_MIN.risk).toBe(480);
    expect(EXPECTED_INTERVALS_MIN.dashboard).toBe(480);
    expect(EXPECTED_INTERVALS_MS.market).toBe(480 * 60_000);
  });
});
