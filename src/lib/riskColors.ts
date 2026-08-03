import type { FreshnessStatus, MarketRegime, RiskLevel } from "@/schemas";

/**
 * 风险语义色映射（架构 §8.6）。
 * 颜色不得是唯一表达：所有使用处必须配文本 + 图标 + 数值。
 * 返回 Tailwind 语义 token 类名（定义于 index.css / tailwind.config.ts）。
 */

export type RiskTone = "low" | "caution" | "high" | "severe" | "na";

/** 风险等级 → 语义色。 */
export function riskLevelTone(level: RiskLevel): RiskTone {
  switch (level) {
    case "risk_on":
    case "low_risk":
      return "low";
    case "caution":
      return "caution";
    case "high_risk":
      return "high";
    case "severe_risk":
    case "crisis":
      return "severe";
    default:
      return "na";
  }
}

export interface ToneClasses {
  text: string;
  bg: string;
  border: string;
  /** 配合 bg 使用的半透明背景（如进度条轨道）。 */
  softBg: string;
}

const TONE_CLASSES: Record<RiskTone, ToneClasses> = {
  low: {
    text: "text-risk-low",
    bg: "bg-risk-low",
    border: "border-risk-low",
    softBg: "bg-risk-low/10",
  },
  caution: {
    text: "text-risk-caution",
    bg: "bg-risk-caution",
    border: "border-risk-caution",
    softBg: "bg-risk-caution/10",
  },
  high: {
    text: "text-risk-high",
    bg: "bg-risk-high",
    border: "border-risk-high",
    softBg: "bg-risk-high/10",
  },
  severe: {
    text: "text-risk-severe",
    bg: "bg-risk-severe",
    border: "border-risk-severe",
    softBg: "bg-risk-severe/10",
  },
  na: {
    text: "text-risk-na",
    bg: "bg-risk-na",
    border: "border-risk-na",
    softBg: "bg-risk-na/10",
  },
};

export function toneClasses(tone: RiskTone): ToneClasses {
  return TONE_CLASSES[tone];
}

export function riskLevelClasses(level: RiskLevel): ToneClasses {
  return toneClasses(riskLevelTone(level));
}

/** 市场状态 → 语义色（risk_on/低风险为绿，危机为红）。 */
export function regimeTone(regime: MarketRegime): RiskTone {
  switch (regime) {
    case "goldilocks":
    case "risk_on":
    case "disinflation":
      return "low";
    case "reflation":
    case "late_cycle":
      return "caution";
    case "stagflation":
    case "liquidity_stress":
    case "risk_off":
      return "high";
    case "crisis":
      return "severe";
    default:
      return "na";
  }
}

/** 资产涨跌方向色：上涨绿/下跌红/平灰（金融惯例，配文本+符号）。 */
export function changeTone(value: number | null | undefined): RiskTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "na";
  if (value > 0) return "low";
  if (value < 0) return "severe";
  return "na";
}

/** 风险趋势（分数变化）：上升=橙（风险增）/下降=绿（风险降）。 */
export function riskTrendTone(value: number | null | undefined): RiskTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "na";
  if (value > 0) return "high";
  if (value < 0) return "low";
  return "na";
}

/** freshness → 语义色。 */
export function freshnessTone(status: FreshnessStatus): RiskTone {
  switch (status) {
    case "fresh":
      return "low";
    case "delayed":
    case "degraded":
      return "caution";
    case "stale":
      return "high";
    case "missing":
      return "na";
    default:
      return "na";
  }
}
