import type { FreshnessStatus, MarketRegime, RiskLevel } from "@/schemas";

/**
 * Semantic color families (ADR-0002; architecture §8.6).
 * Three dedicated families replace the legacy single overloaded ramp:
 * - risk-*  (RiskTone): risk level + market regime ONLY — the only saturated colors at rest
 * - dir-*   (DirTone):  price/asset direction — muted, always paired with an explicit sign
 * - fresh-* (FreshTone): data freshness — icon + text; fresh uses no saturated color
 * Color must not be the only expression: every usage must pair it with text + icon + value.
 * Returns Tailwind semantic token class names (defined in index.css / tailwind.config.ts).
 */

/* ================= Risk family (risk level + regime) ================= */

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

const RISK_TONE_CLASSES: Record<RiskTone, ToneClasses> = {
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
  return RISK_TONE_CLASSES[tone];
}

export function riskLevelClasses(level: RiskLevel): ToneClasses {
  return toneClasses(riskLevelTone(level));
}

/** Market regime → risk ramp (regime is a risk semantic). */
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

/** Risk trend (score change): rising = high tone (risk increasing) / falling = low tone. */
export function riskTrendTone(value: number | null | undefined): RiskTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "na";
  if (value > 0) return "high";
  if (value < 0) return "low";
  return "na";
}

/* ================= Direction family (price/asset change) ================= */

export type DirTone = "up" | "down" | "flat";

/**
 * Asset change direction: up = muted green / down = muted red / flat or missing = neutral.
 * Global Western convention (ADR-0002). Always pair with an explicit +/− sign.
 */
export function dirTone(value: number | null | undefined): DirTone {
  if (value === null || value === undefined || Number.isNaN(value)) return "flat";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

const DIR_TONE_CLASSES: Record<DirTone, ToneClasses> = {
  up: {
    text: "text-dir-up",
    bg: "bg-dir-up",
    border: "border-dir-up",
    softBg: "bg-dir-up/10",
  },
  down: {
    text: "text-dir-down",
    bg: "bg-dir-down",
    border: "border-dir-down",
    softBg: "bg-dir-down/10",
  },
  flat: {
    text: "text-muted-foreground",
    bg: "bg-muted",
    border: "border-hairline",
    softBg: "bg-muted/40",
  },
};

export function dirClasses(tone: DirTone): ToneClasses {
  return DIR_TONE_CLASSES[tone];
}

/* ================= Freshness family (data staleness) ================= */

export type FreshTone = "ok" | "warn" | "bad" | "na";

/**
 * Freshness → treatment. "Fresh" is the expected state and earns no saturated
 * color (muted); only stale/missing get a warm tone. Always pair with icon + text.
 */
export function freshTone(status: FreshnessStatus): FreshTone {
  switch (status) {
    case "fresh":
      return "ok";
    case "delayed":
    case "degraded":
    case "stale":
      return "warn";
    case "missing":
      return "bad";
    default:
      return "na";
  }
}

const FRESH_TONE_CLASSES: Record<FreshTone, ToneClasses> = {
  ok: {
    text: "text-fresh-ok",
    bg: "bg-fresh-ok",
    border: "border-fresh-ok",
    softBg: "bg-fresh-ok/10",
  },
  warn: {
    text: "text-fresh-warn",
    bg: "bg-fresh-warn",
    border: "border-fresh-warn",
    softBg: "bg-fresh-warn/10",
  },
  bad: {
    text: "text-fresh-bad",
    bg: "bg-fresh-bad",
    border: "border-fresh-bad",
    softBg: "bg-fresh-bad/10",
  },
  na: {
    text: "text-muted-foreground",
    bg: "bg-muted",
    border: "border-hairline",
    softBg: "bg-muted/40",
  },
};

export function freshClasses(tone: FreshTone): ToneClasses {
  return FRESH_TONE_CLASSES[tone];
}
