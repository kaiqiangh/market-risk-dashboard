import type { Config } from "tailwindcss";

/**
 * Tailwind configuration.
 * All colors are semantic tokens (CSS variables) defined in src/index.css
 * under :root/.dark and .light, stored as bare "R G B" channel triplets.
 * Every color below is wrapped in rgb( var(...) / <alpha-value> ) — bare
 * var() would resolve to `background-color: 255 255 255`, which is NOT a
 * valid color (no rgb() function), so surfaces would render transparent.
 * The wrapper makes both `bg-card` and `bg-card/10` emit valid CSS.
 * Color families (ADR-0002):
 * - risk-*  risk level + regime only (muted ramp, the only saturated colors at rest)
 * - dir-*   price direction (de-emphasized, always paired with an explicit sign)
 * - fresh-* data freshness (fresh uses no saturated color)
 * Color is never the only expression; always pair with text + icon + value (architecture §8.6).
 * Numerals: use the built-in `tabular-nums` utility on every numeric readout (CONTEXT.md).
 */
const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surface levels (CONTEXT.md): 0 = app bg / open chart regions, 1 = cards, 2 = overlays
        "surface-0": "rgb(var(--surface-0) / <alpha-value>)",
        "surface-1": "rgb(var(--surface-1) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2) / <alpha-value>)",
        hairline: "rgb(var(--hairline) / <alpha-value>)",
        // Risk semantic ramp — risk level + regime ONLY
        risk: {
          low: "rgb(var(--risk-low) / <alpha-value>)",
          caution: "rgb(var(--risk-caution) / <alpha-value>)",
          high: "rgb(var(--risk-high) / <alpha-value>)",
          severe: "rgb(var(--risk-severe) / <alpha-value>)",
          na: "rgb(var(--risk-na) / <alpha-value>)",
        },
        // Price direction — muted, always with an explicit +/− sign
        dir: {
          up: "rgb(var(--dir-up) / <alpha-value>)",
          down: "rgb(var(--dir-down) / <alpha-value>)",
        },
        // Data freshness — ok is muted by design (expected state, no color budget)
        fresh: {
          ok: "rgb(var(--fresh-ok) / <alpha-value>)",
          warn: "rgb(var(--fresh-warn) / <alpha-value>)",
          bad: "rgb(var(--fresh-bad) / <alpha-value>)",
        },
        // Legacy semantic aliases
        background: "rgb(var(--background) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        "card-foreground": "rgb(var(--card-foreground) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        "muted-foreground": "rgb(var(--muted-foreground) / <alpha-value>)",
        border: "rgb(var(--border) / <alpha-value>)",
        input: "rgb(var(--input) / <alpha-value>)",
        primary: "rgb(var(--primary) / <alpha-value>)",
        "primary-foreground": "rgb(var(--primary-foreground) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-foreground": "rgb(var(--accent-foreground) / <alpha-value>)",
        destructive: "rgb(var(--destructive) / <alpha-value>)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 1px)",
        sm: "calc(var(--radius) - 2px)",
      },
    },
  },
  plugins: [],
};

export default config;
