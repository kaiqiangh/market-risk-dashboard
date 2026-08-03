/**
 * Frontend mirror of the asset pool (architecture §8.10/§8.11, corresponds to config/universe.yaml).
 * Display only: card filter order, theme grouping, A-share names. Data values always come from public/data (single source of truth).
 */

/** Key US equities pool (frozen for MVP G2): Cross-Asset card + card-level indicators. */
export const KEY_US_STOCKS: readonly string[] = ["NVDA", "AVGO", "MU", "AMD", "TSLA"];

/** A-share memory pool (suggested codes; universe.yaml is the single source of truth, actually validated in T03). */
export const A_SHARE_STOCKS: readonly { symbol: string; name: string }[] = [
  { symbol: "603986.SH", name: "兆易创新" },
  { symbol: "301308.SZ", name: "江波龙" },
  { symbol: "688525.SH", name: "佰维存储" },
  { symbol: "000021.SZ", name: "深科技" },
  { symbol: "300223.SZ", name: "北京君正" },
  { symbol: "001309.SZ", name: "德明利" },
  { symbol: "300475.SZ", name: "香农芯创" },
  { symbol: "688008.SH", name: "澜起科技" },
  { symbol: "600584.SH", name: "长电科技" },
  { symbol: "002156.SZ", name: "通富微电" },
];

/** Crypto watchlist pool. */
export const CRYPTO_SYMBOLS: readonly string[] = ["BTC", "ETH", "SOL"];

/** Cross-asset heatmap matrix (category → assets). Categories are rendered via i18n; only keys are defined here. */
export const HEATMAP_CATEGORIES: readonly { category: string; assets: readonly string[] }[] = [
  { category: "equities.us", assets: ["NVDA", "AVGO", "MU", "AMD", "TSLA"] },
  { category: "equities.memory", assets: ["603986.SH", "301308.SZ", "688525.SH", "000021.SZ"] },
  { category: "crypto.crypto", assets: ["BTC", "ETH", "SOL"] },
];
