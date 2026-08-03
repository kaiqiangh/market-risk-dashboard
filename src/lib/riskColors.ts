import type { FreshnessStatus, MarketRegime, RiskLevel } from "@/schemas";

/**
 * Risk semantic color mapping (architecture §8.6).
 * Color must not be the only expression: every usage must pair it with text + icon + value.
 * Returns Tailwind semantic token class names (defined in index.css / tailwind.config.ts).
 */

export type RiskTone = "low" | "caution" | "high" | "severe" | "na";

/** Risk level → semantic color. */
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
  /** Translucent background used with bg (e.g. progress bar track). */
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

/** Market regime → semantic color (risk_on / low risk = green, crisis = red). */
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

/** Asset change direction color: up = green / down = red / flat = gray (financial convention, paired with text + sign). */
export function changeTone(value: number | null | undefined): RiskTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "na";
  if (value > 0) return "low";
  if (value < 0) return "severe";
  return "na";
}

/** Risk trend (score change): rising = orange (risk increasing) / falling = green (risk decreasing). */
export function riskTrendTone(value: number | null | undefined): RiskTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "na";
  if (value > 0) return "high";
  if (value < 0) return "low";
  return "na";
}

/** freshness → semantic color. */
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
