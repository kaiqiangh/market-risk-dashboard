/**
 * Frontend mirror of the asset pool (architecture §8.10/§8.11, corresponds to config/universe.yaml).
 * Display only: card filter order, theme grouping, A-share names. Data values always come from public/data (single source of truth).
 */

/** Key US equities pool (frozen for MVP G2): Cross-Asset card + card-level indicators. */
export const KEY_US_STOCKS: readonly string[] = ["NVDA", "AVGO", "MU", "AMD", "TSLA"];
