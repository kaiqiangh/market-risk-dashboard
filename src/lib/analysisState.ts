import type { AnalysisDataset, FactLayer, FreshnessStatus } from "@/schemas";

/** Reasons the homepage can explain why a bilingual AI brief is not publishable as fresh. */
export type AnalysisNotice =
  | "analysisMissing"
  | "analysisMalformed"
  | "pairIncomplete"
  | "pairMismatch"
  | "factsMissing"
  | "factsUnidentified"
  | "lineageMissing"
  | "lineageMismatch"
  | "inputUnhealthy"
  | "delayed"
  | "stale"
  | "empty";

export interface AnalysisPresentation {
  /** The current-locale brief is exposed only after the pair passes all lineage checks. */
  analysis?: AnalysisDataset;
  status: FreshnessStatus;
  notice: AnalysisNotice | null;
  validated: boolean;
}

export interface AnalysisPairInput {
  current?: AnalysisDataset;
  alternate?: AnalysisDataset;
  facts?: FactLayer;
  currentError?: Error | null;
  alternateError?: Error | null;
  factsError?: Error | null;
}

const STATUS_RANK: Record<FreshnessStatus, number> = {
  fresh: 0,
  delayed: 1,
  stale: 2,
  empty: 3,
  degraded: 4,
  missing: 5,
};

const PARALLEL_ARRAY_FIELDS = [
  "top_risk_drivers",
  "supporting_signals",
  "contradicting_signals",
  "what_changed_today",
  "watch_next",
] as const;

const REQUIRED_FACT_INPUTS = [
  "macro",
  "equities",
  "sectors",
  "crypto",
  "news",
  "calendar",
  "risk",
] as const;

function worstStatus(statuses: FreshnessStatus[]): FreshnessStatus {
  return statuses.reduce(
    (worst, status) => (STATUS_RANK[status] > STATUS_RANK[worst] ? status : worst),
    "fresh" as FreshnessStatus,
  );
}

function recordsEqual(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  const keys = [...new Set([...Object.keys(left), ...Object.keys(right)])].sort();
  return keys.every((key) => left[key] === right[key]);
}

function evidenceKey(ref: { dataset: string; path: string; metric: string; value: number | string }): string {
  const value = typeof ref.value === "number" ? ref.value.toFixed(6) : String(ref.value);
  return `${ref.dataset}|${ref.path}|${ref.metric}|${value}`;
}

function evidenceKeys(analysis: AnalysisDataset): string[] {
  const refs = [
    ...analysis.evidence_refs,
    ...analysis.top_risk_drivers.flatMap((claim) => claim.evidence_refs),
    ...analysis.supporting_signals.flatMap((claim) => claim.evidence_refs),
    ...analysis.contradicting_signals.flatMap((claim) => claim.evidence_refs),
    ...analysis.bull_case.evidence_refs,
    ...analysis.base_case.evidence_refs,
    ...analysis.bear_case.evidence_refs,
  ];
  return refs.map(evidenceKey).sort();
}

function extractNumbers(text: string): number[] {
  return (text.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number).sort((a, b) => a - b);
}

function textNumbersMatch(current: AnalysisDataset, alternate: AnalysisDataset): boolean {
  const pairs: Array<[string, string]> = [
    [current.summary, alternate.summary],
    [current.bull_case.title, alternate.bull_case.title],
    [current.base_case.title, alternate.base_case.title],
    [current.bear_case.title, alternate.bear_case.title],
  ];
  for (const [currentLines, alternateLines] of [
    [current.what_changed_today, alternate.what_changed_today],
    [current.watch_next, alternate.watch_next],
    [current.bull_case.points, alternate.bull_case.points],
    [current.base_case.points, alternate.base_case.points],
    [current.bear_case.points, alternate.bear_case.points],
  ] as const) {
    if (currentLines.length !== alternateLines.length) return false;
    pairs.push(...currentLines.map((line, index) => [line, alternateLines[index]] as [string, string]));
  }
  for (const [currentClaims, alternateClaims] of [
    [current.top_risk_drivers, alternate.top_risk_drivers],
    [current.supporting_signals, alternate.supporting_signals],
    [current.contradicting_signals, alternate.contradicting_signals],
  ] as const) {
    if (currentClaims.length !== alternateClaims.length) return false;
    pairs.push(...currentClaims.map((claim, index) => [claim.claim, alternateClaims[index].claim] as [string, string]));
  }
  return pairs.every(([currentText, alternateText]) => {
    const currentNumbers = extractNumbers(currentText);
    const alternateNumbers = extractNumbers(alternateText);
    return currentNumbers.length === alternateNumbers.length && currentNumbers.every((value, index) => Math.abs(value - alternateNumbers[index]) < 1e-6);
  });
}

function pairStructureMatches(current: AnalysisDataset, alternate: AnalysisDataset): boolean {
  if (
    current.market_state !== alternate.market_state ||
    current.market_regime !== alternate.market_regime ||
    current.confidence !== alternate.confidence ||
    current.data_freshness !== alternate.data_freshness
  ) {
    return false;
  }

  if (evidenceKeys(current).join("\n") !== evidenceKeys(alternate).join("\n")) return false;
  if (!textNumbersMatch(current, alternate)) return false;
  return PARALLEL_ARRAY_FIELDS.every((field) => current[field].length === alternate[field].length)
    && current.bull_case.points.length === alternate.bull_case.points.length
    && current.base_case.points.length === alternate.base_case.points.length
    && current.bear_case.points.length === alternate.bear_case.points.length;
}

function lineageMatchesFacts(analysis: AnalysisDataset, facts: FactLayer): boolean {
  if (!analysis.lineage || !facts.generation_id) return false;
  return (
    analysis.lineage.fact_generation_id === facts.generation_id &&
    analysis.lineage.fact_generated_at === facts.generated_at &&
    recordsEqual(analysis.lineage.input_freshness, facts.data_freshness)
  );
}

function isMalformed(error: Error | null | undefined): boolean {
  return error?.name === "SchemaError";
}

function state(status: FreshnessStatus, notice: AnalysisNotice): AnalysisPresentation {
  return { status, notice, validated: false };
}

/**
 * Derive the one homepage presentation state from both language files and current facts.
 * Fresh is deliberately unreachable unless every identity and structural check succeeds.
 */
export function deriveAnalysisPresentation(input: AnalysisPairInput): AnalysisPresentation {
  const { current, alternate, facts } = input;

  if (input.currentError) {
    return state(isMalformed(input.currentError) ? "degraded" : "missing", isMalformed(input.currentError) ? "analysisMalformed" : "analysisMissing");
  }
  if (!current) return state("missing", "analysisMissing");

  if (input.alternateError) return state("degraded", isMalformed(input.alternateError) ? "analysisMalformed" : "pairIncomplete");
  if (!alternate) return state("degraded", "pairIncomplete");
  if (input.factsError || !facts) return state("missing", "factsMissing");
  if (!facts.generation_id) return state("degraded", "factsUnidentified");
  if (REQUIRED_FACT_INPUTS.some((key) => !(key in facts.data_freshness))) {
    return state("missing", "factsMissing");
  }

  if (!current.lineage || !alternate.lineage) return state("degraded", "lineageMissing");
  if (
    current.language === alternate.language ||
    current.lineage.pair_id !== alternate.lineage.pair_id ||
    current.lineage.fact_generation_id !== alternate.lineage.fact_generation_id ||
    current.lineage.fact_generated_at !== alternate.lineage.fact_generated_at ||
    !recordsEqual(current.lineage.input_freshness, alternate.lineage.input_freshness) ||
    !lineageMatchesFacts(current, facts) ||
    !lineageMatchesFacts(alternate, facts)
  ) {
    return state("degraded", "lineageMismatch");
  }
  if (!pairStructureMatches(current, alternate)) return state("degraded", "pairMismatch");

  const status = worstStatus([
    current.data_freshness,
    alternate.data_freshness,
    ...Object.values(facts.data_freshness),
  ]);
  if (status !== "fresh") {
    const notice: AnalysisNotice = status === "delayed" ? "delayed" : status === "stale" ? "stale" : status === "empty" ? "empty" : "inputUnhealthy";
    return state(status, notice);
  }

  return { analysis: current, status: "fresh", notice: null, validated: true };
}
