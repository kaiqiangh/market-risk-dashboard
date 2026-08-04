import type { MarketRegime, RiskDimensionKey, RiskLevel, RiskTrend } from "@/schemas";

/**
 * Risk enum → i18n key mapping (architecture §8.7: terminology follows the glossary; no hardcoded UI copy).
 * Keys are **namespace-relative paths** (default risk namespace, used with useTranslation("risk");
 * cross-namespace usages like AIBrief use the explicit `risk:${key}` prefix, which also works).
 * RISK_TREND_KEYS belong to the common namespace and carry an explicit `common:` prefix.
 */

export const RISK_LEVEL_KEYS: Record<RiskLevel, string> = {
  risk_on: "level.riskOn",
  low_risk: "level.lowRisk",
  caution: "level.caution",
  high_risk: "level.highRisk",
  severe_risk: "level.severeRisk",
  crisis: "level.crisis",
};

export const REGIME_KEYS: Record<MarketRegime, string> = {
  goldilocks: "regime.goldilocks",
  risk_on: "regime.riskOn",
  disinflation: "regime.disinflation",
  reflation: "regime.reflation",
  late_cycle: "regime.lateCycle",
  stagflation: "regime.stagflation",
  liquidity_stress: "regime.liquidityStress",
  risk_off: "regime.riskOff",
  crisis: "regime.crisis",
  indeterminate: "regime.indeterminate",
};

export const RISK_DIMENSION_KEYS: Record<RiskDimensionKey, string> = {
  macro: "dim.macro",
  liquidity_credit: "dim.liquidityCredit",
  equity_structure: "dim.equityStructure",
  volatility: "dim.volatility",
  cross_asset: "dim.crossAsset",
  trend: "dim.trend",
};

export const RISK_TREND_KEYS: Record<RiskTrend, string> = {
  rising: "common:direction.rising",
  falling: "common:direction.falling",
  flat: "common:direction.flat",
};

/** market_state in the analysis file matches the risk level enum; map loosely to guard against unknown values. */
export function riskLevelKey(level: string): string {
  return RISK_LEVEL_KEYS[level as RiskLevel] ?? "level.caution";
}

/** market_regime in the analysis file matches the enum; map loosely to guard against unknown values. */
export function regimeKey(regime: string): string {
  return REGIME_KEYS[regime as MarketRegime] ?? "regime.riskOff";
}
