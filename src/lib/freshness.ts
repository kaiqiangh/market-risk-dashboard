import type { FreshnessStatus } from "@/schemas";

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
