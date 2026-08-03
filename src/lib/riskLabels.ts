import type { MarketRegime, RiskDimensionKey, RiskLevel, RiskTrend } from "@/schemas";

/**
 * 风险枚举 → i18n key 映射（架构 §8.7：术语遵循 glossary；禁止硬编码 UI 文案）。
 * key 为**命名空间相对路径**（默认 risk 命名空间，随 useTranslation("risk") 使用；
 * AIBrief 等跨命名空间处用 `risk:${key}` 显式前缀，同样成立）。
 * RISK_TREND_KEYS 属于 common 命名空间，显式带 `common:` 前缀。
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

/** 分析文件里的 market_state 与风险等级枚举一致；宽松映射以防未知值。 */
export function riskLevelKey(level: string): string {
  return RISK_LEVEL_KEYS[level as RiskLevel] ?? "level.caution";
}

/** 分析文件里的 market_regime 与枚举一致；宽松映射以防未知值。 */
export function regimeKey(regime: string): string {
  return REGIME_KEYS[regime as MarketRegime] ?? "regime.riskOff";
}
