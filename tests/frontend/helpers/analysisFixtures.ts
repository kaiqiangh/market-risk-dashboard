import analysisZhGolden from "../../fixtures/analysis.zh-CN.json";
import { analysisEnFixture } from "./fixtureData";

export const analysisLineageFixture = {
  fact_generation_id: "sha256:4507ebe867d1146d235294deb6685549e008d60735cccead8ce95c1a1da0a5f0",
  fact_generated_at: "2026-08-03T10:00:00Z",
  input_freshness: {
    macro: "fresh",
    equities: "fresh",
    sectors: "fresh",
    crypto: "fresh",
    news: "fresh",
    calendar: "fresh",
    risk: "fresh",
  },
  pair_id: "fixture-analysis-pair-v2",
} as const;

/** A valid frontend pair layered over the schema golden without changing the Python golden. */
export const analysisZhFixture = {
  ...analysisZhGolden,
  lineage: analysisLineageFixture,
};

export { analysisEnFixture };
