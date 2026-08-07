import type { FreshnessStatus } from "@/schemas";
import CONTRACT_CONSTANTS from "@/schemas/generated/constants.json";

/**
 * Freshness semantics and UI (architecture §8.5, six states after #89).
 * Classification (relative to the expected update frequency):
 *   fresh    ≤ 1.5× expected interval, payload non-empty → normal display
 *   delayed  1.5× ~ 3×                                   → yellow warning
 *   stale    > 3×                                        → clear warning + "stale" data badge
 *   empty    collected fine, nothing came back           → empty state, but the run succeeded
 *   missing  never had data                              → empty state (EmptyState)
 *   degraded partial provider degradation/fallback (time-independent) → lower confidence + badge
 *
 * `empty` and `missing` look the same on screen and mean opposite things to an operator:
 * `empty` is "we asked and the answer was nothing", `missing` is "we never got to ask".
 * The distinction is carried by the reason code, not by the badge.
 */

/**
 * Expected update interval (minutes), keyed by canonical dataset key.
 *
 * Read from the generated contract constants, which are produced from
 * config/sources.yaml:expectations (#101). This table used to be typed out here by hand
 * and drifted from the pipeline: it was keyed by UI grouping ("market") rather than by
 * dataset key, so `finalize_freshness("equities")` looked up an expectation that did not
 * exist and every equities run silently used a fallback interval.
 */
export const EXPECTED_INTERVALS_MIN: Record<string, number> = buildExpectedIntervals();

function buildExpectedIntervals(): Record<string, number> {
  const byKey: Record<string, number> = { ...CONTRACT_CONSTANTS.expected_interval_minutes };
  // Domain aliases: history series and the status page address data by provider domain
  // ("market" covers equities + sectors), not by dataset key. A domain is only as fresh as
  // its most demanding dataset, so take the minimum instead of inventing a second number.
  for (const [domain, keys] of Object.entries(CONTRACT_CONSTANTS.domain_datasets)) {
    if (domain in byKey) continue;
    const intervals = (keys as string[])
      .map((key) => byKey[key])
      .filter((value): value is number => typeof value === "number");
    if (intervals.length > 0) byKey[domain] = Math.min(...intervals);
  }
  return byKey;
}

/** Expected update interval (ms) — derived from EXPECTED_INTERVALS_MIN. */
export const EXPECTED_INTERVALS_MS: Record<string, number> = Object.fromEntries(
  Object.entries(EXPECTED_INTERVALS_MIN).map(([key, minutes]) => [key, minutes * 60_000]),
);

/**
 * Fallback interval for a key with no registered expectation (8h, the cadence of the
 * market datasets). Only reachable for keys outside the registry — a registered dataset
 * always has an expectation, because gen_ts_contracts.py refuses to emit constants when
 * config/sources.yaml:expectations and the registry disagree.
 */
export const DEFAULT_EXPECTED_INTERVAL_MIN = 480;

/** Expected interval (ms) for a dataset key. */
export function expectedIntervalMsFor(key: string): number {
  return EXPECTED_INTERVALS_MS[key] ?? DEFAULT_EXPECTED_INTERVAL_MIN * 60_000;
}

/**
 * Time-dimension classification. Returns only the three time-derived states plus
 * `missing`; `empty` and `degraded` are not observable from a timestamp and come from
 * the envelope.
 */
export function evaluateFreshness(
  updatedAt: string | null,
  expectedIntervalMs: number,
  now: number = Date.now(),
): FreshnessStatus {
  if (!updatedAt) return "missing";
  const t = Date.parse(updatedAt);
  if (Number.isNaN(t)) return "missing";
  const age = now - t;
  if (age <= 1.5 * expectedIntervalMs) return "fresh";
  if (age <= 3.0 * expectedIntervalMs) return "delayed";
  return "stale";
}

export type BadgeTone = "success" | "warning" | "danger" | "neutral";

export interface FreshnessBadge {
  status: FreshnessStatus;
  /** i18n key (common namespace, e.g. common:status.fresh) */
  labelKey: string;
  tone: BadgeTone;
  /** Whether a prominent warning is needed */
  prominent: boolean;
  /** UI semantic description (architecture §8.5 table) */
  descriptionKey: string;
}

const BADGE_MAP: Record<FreshnessStatus, FreshnessBadge> = {
  fresh: {
    status: "fresh",
    labelKey: "status.fresh",
    tone: "success",
    prominent: false,
    descriptionKey: "status.freshDesc",
  },
  delayed: {
    status: "delayed",
    labelKey: "status.delayed",
    tone: "warning",
    prominent: false,
    descriptionKey: "status.delayedDesc",
  },
  stale: {
    status: "stale",
    labelKey: "status.stale",
    tone: "danger",
    prominent: true,
    descriptionKey: "status.staleDesc",
  },
  // Not prominent: an empty calendar week or a quiet news window is a normal outcome,
  // and shouting about it trains the reader to ignore the badge. The page still renders
  // an empty state, and the reason code says which kind of nothing this is.
  empty: {
    status: "empty",
    labelKey: "status.empty",
    tone: "neutral",
    prominent: false,
    descriptionKey: "status.emptyDesc",
  },
  missing: {
    status: "missing",
    labelKey: "status.missing",
    tone: "neutral",
    prominent: false,
    descriptionKey: "status.missingDesc",
  },
  degraded: {
    status: "degraded",
    labelKey: "status.degraded",
    tone: "warning",
    prominent: true,
    descriptionKey: "status.degradedDesc",
  },
};

/** Freshness state → UI badge/notice. */
export function badgeFor(status: FreshnessStatus, fromCache = false): FreshnessBadge {
  // #66: a cache replay is visibly distinct from a live-but-delayed fetch. The freshness
  // status is degraded, but the reader needs to know the numbers are REPLAYED, not fresh-ish.
  if (fromCache) {
    return {
      status: "degraded",
      labelKey: "status.cacheReplay",
      tone: "neutral",
      prominent: false,
      descriptionKey: "status.cacheReplayDesc",
    };
  }
  return BADGE_MAP[status];
}

/**
 * staleTime (ms): how long react-query treats a cached response as current. This is a
 * client polling concern, not a data contract — it is deliberately NOT derived from
 * expected_interval_minutes, which describes how often the pipeline publishes.
 * An unregistered key falls back to 60s, which only costs an extra refetch.
 */
export const DEFAULT_STALE_TIME_MS = 60_000;
export const DATASET_STALE_TIME_MS: Record<string, number> = {
  macro: 10 * 60_000,
  calendar: 15 * 60_000,
  analysis: 10 * 60_000,
  market: 5 * 60_000,
  news: 5 * 60_000,
  news_translations: 10 * 60_000,
  risk: 5 * 60_000,
  dashboard: 5 * 60_000,
  equities: 5 * 60_000,
  sectors: 5 * 60_000,
  crypto: 5 * 60_000,
  factlayer: 5 * 60_000,
};

/** Return staleTime by dataset key (falls back to the default 60s when unregistered). */
export function staleTimeFor(key: string): number {
  return DATASET_STALE_TIME_MS[key] ?? DEFAULT_STALE_TIME_MS;
}

/**
 * Merge envelope.freshness_status with the time-dimension classification.
 *
 * Does stale override degraded? No: degraded/empty/missing are statements about what the
 * pipeline observed, and the clock cannot contradict them. Only the fresh/delayed states
 * can be demoted by age.
 *
 * `datasetKey` selects the expectation. It used to be hardcoded to the "market" interval
 * for every dataset, which meant the calendar (published daily) was judged against an
 * 8-hour clock and looked stale from the moment it was published.
 */
export function effectiveStatus(
  envelopeStatus: FreshnessStatus,
  updatedAt: string | null,
  datasetKey: string,
): FreshnessStatus {
  if (envelopeStatus === "degraded" || envelopeStatus === "missing" || envelopeStatus === "empty") {
    return envelopeStatus;
  }
  const computed = evaluateFreshness(updatedAt, expectedIntervalMsFor(datasetKey));
  if (computed === "stale") return "stale";
  return envelopeStatus;
}
