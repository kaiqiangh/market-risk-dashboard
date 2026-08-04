import type { FreshnessStatus } from "@/schemas/envelope";

/**
 * Freshness five-state semantics and UI (architecture §8.5).
 * Classification (relative to the expected update frequency):
 *   fresh   ≤ 1.5× expected interval → normal display
 *   delayed 1.5× ~ 3×       → yellow warning
 *   stale   > 3×            → clear warning + "stale" data badge
 *   missing never had data  → empty state (EmptyState)
 *   degraded partial provider degradation/fallback (time-independent) → lower confidence + "degraded" badge
 */

/**
 * Expected update interval (minutes) — kept in sync with config/sources.yaml expectations (frozen G4,
 * Fix P2-10: frontend synced after the pipeline adds the risk/dashboard domains; tests include a sync test to prevent drift).
 */
export const EXPECTED_INTERVALS_MIN: Record<string, number> = {
  market: 480, // market/news 2-3 times/day
  news: 480,
  macro: 240, // macro 2-4h
  calendar: 1440, // earnings calendar 1 time/day
  analysis: 720, // AI brief 2 times/day
  risk: 480, // risk model recomputed 2-3 times/day with the pipeline
  dashboard: 480, // dashboard aggregation recomputed 2-3 times/day with the pipeline
};

/** Expected update interval (ms) — derived from EXPECTED_INTERVALS_MIN. */
export const EXPECTED_INTERVALS_MS: Record<string, number> = Object.fromEntries(
  Object.entries(EXPECTED_INTERVALS_MIN).map(([key, minutes]) => [key, minutes * 60_000]),
) as Record<string, number>;

/** Time-dimension five-state classification (does not include degraded; degraded comes directly from envelope.freshness_status). */
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

/** Five states → UI badge/notice. */
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
 * staleTime (ms): based on dataset freshness semantics (Fix P2-10, architecture §3.6).
 * High-frequency domains (market/news/risk) are short; low-frequency domains (macro/calendar) are long; analysis follows the brief cadence.
 */
export const DEFAULT_STALE_TIME_MS = 60_000;
export const DATASET_STALE_TIME_MS: Record<string, number> = {
  macro: 10 * 60_000,
  calendar: 15 * 60_000,
  analysis: 10 * 60_000,
  market: 5 * 60_000,
  news: 5 * 60_000,
  risk: 5 * 60_000,
  dashboard: 5 * 60_000,
  equities: 5 * 60_000,
  sectors: 5 * 60_000,
  crypto: 5 * 60_000,
};

/** Return staleTime by dataset key (falls back to the default 60s when unregistered). */
export function staleTimeFor(key: string): number {
  return DATASET_STALE_TIME_MS[key] ?? DEFAULT_STALE_TIME_MS;
}

/** Merge envelope.freshness_status with the time-dimension classification (does stale override degraded? No: degraded is a degradation semantic and keeps the envelope value). */
export function effectiveStatus(envelopeStatus: FreshnessStatus, updatedAt: string | null): FreshnessStatus {
  if (envelopeStatus === "degraded" || envelopeStatus === "missing") return envelopeStatus;
  const computed = evaluateFreshness(updatedAt, EXPECTED_INTERVALS_MS.market);
  if (computed === "stale") return "stale";
  return envelopeStatus;
}
