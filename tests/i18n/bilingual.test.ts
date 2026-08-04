/**
 * Bilingual AI conclusion consistency tests (PRD §25.2: bilingual AI conclusion consistency / architecture §3.4).
 * Based on the analysis.zh-CN.json golden (tests/fixtures/) and the hand-written English document
 * in tests/frontend/helpers/fixtureData.ts (the static analysis.en.json was deleted by #73):
 * market_state / market_regime / confidence / evidence_refs set / list lengths must match;
 * only the prose language differs. The full bilingual validation on the pytest side is in
 * pipeline/analysis/validate.py.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { analysisEnFixture } from "../frontend/helpers/fixtureData";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fixturesDir = path.resolve(__dirname, "../fixtures");

interface EvidenceRef {
  dataset: string;
  path: string;
  metric: string;
  value: number | string;
}

interface SignalClaim {
  claim: string;
  evidence_refs: EvidenceRef[];
}

interface CaseStatement {
  title: string;
  points: string[];
  evidence_refs: EvidenceRef[];
}

interface AnalysisFixture {
  schema_version: string;
  generated_at: string;
  language: string;
  market_state: string;
  market_regime: string;
  confidence: number;
  summary: string;
  top_risk_drivers: SignalClaim[];
  supporting_signals: SignalClaim[];
  contradicting_signals: SignalClaim[];
  what_changed_today: string[];
  watch_next: string[];
  bull_case: CaseStatement;
  base_case: CaseStatement;
  bear_case: CaseStatement;
  evidence_refs: EvidenceRef[];
}

function loadAnalysis(lang: "zh-CN" | "en"): AnalysisFixture {
  // The en document is no longer a committed file (#73): it is the hand-written inline
  // document shared by the frontend suite, bilingually consistent with the zh-CN golden.
  if (lang === "en") return analysisEnFixture as unknown as AnalysisFixture;
  const p = path.join(fixturesDir, `analysis.${lang}.json`);
  return JSON.parse(readFileSync(p, "utf-8")) as AnalysisFixture;
}

function refKey(ref: EvidenceRef): string {
  const value = typeof ref.value === "number" ? ref.value.toFixed(6) : String(ref.value);
  return `${ref.dataset}|${ref.path}|${ref.metric}|${value}`;
}

function collectRefs(a: AnalysisFixture): string[] {
  const refs = [...a.evidence_refs];
  for (const claim of [...a.top_risk_drivers, ...a.supporting_signals, ...a.contradicting_signals]) {
    refs.push(...claim.evidence_refs);
  }
  for (const c of [a.bull_case, a.base_case, a.bear_case]) refs.push(...c.evidence_refs);
  return refs.map(refKey).sort();
}

function extractNumbers(text: string): number[] {
  const matches = text.match(/-?\d+(?:\.\d+)?/g) ?? [];
  return matches.map(Number).sort((x, y) => x - y);
}

describe("bilingual AI conclusion consistency", () => {
  const zh = loadAnalysis("zh-CN");
  const en = loadAnalysis("en");

  it("language fields are correct", () => {
    expect(zh.language).toBe("zh-CN");
    expect(en.language).toBe("en");
  });

  it("market_state / market_regime match exactly", () => {
    expect(zh.market_state).toBe(en.market_state);
    expect(zh.market_regime).toBe(en.market_regime);
  });

  it("confidence matches exactly", () => {
    expect(zh.confidence).toBe(en.confidence);
  });

  it("evidence_refs sets match exactly", () => {
    expect(collectRefs(zh)).toEqual(collectRefs(en));
  });

  it("parallel list lengths match (structural equivalence)", () => {
    expect(zh.top_risk_drivers.length).toBe(en.top_risk_drivers.length);
    expect(zh.supporting_signals.length).toBe(en.supporting_signals.length);
    expect(zh.contradicting_signals.length).toBe(en.contradicting_signals.length);
    expect(zh.what_changed_today.length).toBe(en.what_changed_today.length);
    expect(zh.watch_next.length).toBe(en.watch_next.length);
    expect(zh.bull_case.points.length).toBe(en.bull_case.points.length);
    expect(zh.base_case.points.length).toBe(en.base_case.points.length);
    expect(zh.bear_case.points.length).toBe(en.bear_case.points.length);
  });

  it("number sets in text match (rounding tolerated)", () => {
    const pairs: Array<[string, string]> = [
      [zh.summary, en.summary],
      [zh.bull_case.title, en.bull_case.title],
      [zh.base_case.title, en.base_case.title],
      [zh.bear_case.title, en.bear_case.title],
    ];
    zh.what_changed_today.forEach((t, i) => pairs.push([t, en.what_changed_today[i]]));
    zh.watch_next.forEach((t, i) => pairs.push([t, en.watch_next[i]]));
    for (const [z, e] of pairs) {
      const zNums = extractNumbers(z);
      const eNums = extractNumbers(e);
      expect(zNums.length, `zh=${z!} / en=${e!}`).toBe(eNums.length);
      zNums.forEach((n, i) => expect(Math.abs(n - eNums[i])).toBeLessThan(1e-6));
    }
  });
});
