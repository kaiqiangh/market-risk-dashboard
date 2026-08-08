import { describe, expect, it } from "vitest";
import factsFixture from "../fixtures/facts.json";
import { analysisEnFixture, analysisZhFixture } from "./helpers/analysisFixtures";
import { deriveAnalysisPresentation } from "@/lib/analysisState";
import type { AnalysisDataset, FactLayer, FreshnessStatus } from "@/schemas";

const zh = analysisZhFixture as unknown as AnalysisDataset;
const en = analysisEnFixture as unknown as AnalysisDataset;
const facts = factsFixture as unknown as FactLayer;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function withFreshness(status: FreshnessStatus): {
  current: AnalysisDataset;
  alternate: AnalysisDataset;
  facts: FactLayer;
} {
  const current = clone(zh);
  const alternate = clone(en);
  current.data_freshness = status;
  alternate.data_freshness = status;
  return { current, alternate, facts };
}

describe("deriveAnalysisPresentation", () => {
  it("fresh requires a current, matching bilingual lineage pair", () => {
    const result = deriveAnalysisPresentation({ current: zh, alternate: en, facts });

    expect(result).toEqual({ analysis: zh, status: "fresh", notice: null, validated: true });
  });

  it.each([
    ["delayed", "delayed"],
    ["stale", "stale"],
    ["empty", "empty"],
    ["degraded", "inputUnhealthy"],
  ] as const)("does not expose %s content as fresh", (status, notice) => {
    const result = deriveAnalysisPresentation(withFreshness(status));

    expect(result).toMatchObject({ status, notice, validated: false });
    expect(result.analysis).toBeUndefined();
  });

  it("missing current language is localized as unavailable", () => {
    const result = deriveAnalysisPresentation({ currentError: new Error("HTTP 404") });

    expect(result).toMatchObject({ status: "missing", notice: "analysisMissing", validated: false });
  });

  it("malformed current language is degraded, not rendered", () => {
    const error = new Error("contract failed");
    error.name = "SchemaError";
    const result = deriveAnalysisPresentation({ currentError: error });

    expect(result).toMatchObject({ status: "degraded", notice: "analysisMalformed", validated: false });
  });

  it("incomplete pair never becomes a complete brief", () => {
    const result = deriveAnalysisPresentation({ current: zh, facts });

    expect(result).toMatchObject({ status: "degraded", notice: "pairIncomplete", validated: false });
  });

  it("facts are required and must have an identity", () => {
    const missing = deriveAnalysisPresentation({ current: zh, alternate: en });
    const unidentifiedFacts = clone(facts);
    unidentifiedFacts.generation_id = null;
    const unidentified = deriveAnalysisPresentation({ current: zh, alternate: en, facts: unidentifiedFacts });

    expect(missing).toMatchObject({ status: "missing", notice: "factsMissing" });
    expect(unidentified).toMatchObject({ status: "degraded", notice: "factsUnidentified" });
  });

  it("rejects lineage and structural mismatches", () => {
    const lineageMismatch = clone(en);
    lineageMismatch.lineage = { ...lineageMismatch.lineage!, pair_id: "different-pair" };
    const pairMismatch = clone(en);
    pairMismatch.market_regime = "risk_on";
    const lengthMismatch = clone(en);
    lengthMismatch.top_risk_drivers = [];

    expect(deriveAnalysisPresentation({ current: zh, alternate: lineageMismatch, facts })).toMatchObject({
      status: "degraded",
      notice: "lineageMismatch",
    });
    expect(deriveAnalysisPresentation({ current: zh, alternate: pairMismatch, facts })).toMatchObject({
      status: "degraded",
      notice: "pairMismatch",
    });
    expect(deriveAnalysisPresentation({ current: zh, alternate: lengthMismatch, facts })).toMatchObject({
      status: "degraded",
      notice: "pairMismatch",
    });
  });

  it("degraded fact input is surfaced even when the pair identity matches", () => {
    const degradedFacts = clone(facts);
    degradedFacts.data_freshness = { ...degradedFacts.data_freshness, equities: "degraded" };
    degradedFacts.generation_id = "sha256:1111111111111111111111111111111111111111111111111111111111111111";
    const current = clone(zh);
    const alternate = clone(en);
    current.data_freshness = "degraded";
    alternate.data_freshness = "degraded";
    current.lineage = {
      ...current.lineage!,
      fact_generation_id: degradedFacts.generation_id,
      input_freshness: degradedFacts.data_freshness,
    };
    alternate.lineage = {
      ...alternate.lineage!,
      fact_generation_id: degradedFacts.generation_id,
      input_freshness: degradedFacts.data_freshness,
    };
    const result = deriveAnalysisPresentation({ current, alternate, facts: degradedFacts });

    expect(result).toMatchObject({ status: "degraded", notice: "inputUnhealthy", validated: false });
  });
});
