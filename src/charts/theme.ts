/**
 * Chart theme bridge (spec #23 ticket #27).
 * ECharts renders to canvas and cannot consume Tailwind classes, so resolve the
 * semantic CSS variables from index.css at render time. Falls back to the dark
 * palette when variables are unavailable (jsdom / tests).
 * Color rules (ADR-0002): accent for the primary series, risk ramp only for
 * risk semantics (thresholds), dir-* for up/down, hairlines for grid.
 */

function cssVar(name: string, fallback: string, alpha?: number): string {
  if (typeof window === "undefined" || typeof getComputedStyle !== "function") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!raw) return fallback;
  const parts = raw.split(/[\s,]+/).filter(Boolean);
  if (parts.length !== 3) return raw;
  return alpha === undefined ? `rgb(${parts.join(", ")})` : `rgba(${parts.join(", ")}, ${alpha})`;
}

export interface ChartTheme {
  /** Axis labels / secondary text */
  axis: string;
  /** Axis lines + grid split lines (hairline strength) */
  grid: string;
  /** Primary data series (single blue-cyan accent) */
  accent: string;
  /** Primary series area fill (10% accent) */
  accentSoft: string;
  dirUp: string;
  dirDown: string;
  /** Neutral midpoint for diverging scales (surface-2) */
  neutral: string;
  riskLow: string;
  riskCaution: string;
  riskHigh: string;
  riskSevere: string;
  /** Text drawn on top of colored cells */
  onFill: string;
}

export function chartTheme(): ChartTheme {
  return {
    axis: cssVar("--muted-foreground", "rgb(139, 151, 169)"),
    grid: cssVar("--hairline", "rgba(38, 48, 67, 0.6)", 0.6),
    accent: cssVar("--primary", "rgb(107, 163, 201)"),
    accentSoft: cssVar("--primary", "rgba(107, 163, 201, 0.1)", 0.1),
    dirUp: cssVar("--dir-up", "rgb(107, 158, 133)"),
    dirDown: cssVar("--dir-down", "rgb(178, 115, 115)"),
    neutral: cssVar("--surface-2", "rgb(27, 35, 51)"),
    riskLow: cssVar("--risk-low", "rgb(63, 157, 120)"),
    riskCaution: cssVar("--risk-caution", "rgb(201, 160, 74)"),
    riskHigh: cssVar("--risk-high", "rgb(207, 116, 56)"),
    riskSevere: cssVar("--risk-severe", "rgb(204, 82, 82)"),
    onFill: cssVar("--foreground", "rgb(215, 222, 233)"),
  };
}
