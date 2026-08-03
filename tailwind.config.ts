import type { Config } from "tailwindcss";

/**
 * Tailwind configuration.
 * All colors are semantic tokens (CSS variables) defined in src/index.css
 * under :root/.dark and .light. Color families (ADR-0002):
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
        "surface-0": "var(--surface-0)",
        "surface-1": "var(--surface-1)",
        "surface-2": "var(--surface-2)",
        hairline: "var(--hairline)",
        // Risk semantic ramp — risk level + regime ONLY
        risk: {
          low: "var(--risk-low)",
          caution: "var(--risk-caution)",
          high: "var(--risk-high)",
          severe: "var(--risk-severe)",
          na: "var(--risk-na)",
        },
        // Price direction — muted, always with an explicit +/− sign
        dir: {
          up: "var(--dir-up)",
          down: "var(--dir-down)",
        },
        // Data freshness — ok is muted by design (expected state, no color budget)
        fresh: {
          ok: "var(--fresh-ok)",
          warn: "var(--fresh-warn)",
          bad: "var(--fresh-bad)",
        },
        // Legacy semantic aliases
        background: "var(--background)",
        foreground: "var(--foreground)",
        card: "var(--card)",
        "card-foreground": "var(--card-foreground)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        border: "var(--border)",
        input: "var(--input)",
        primary: "var(--primary)",
        "primary-foreground": "var(--primary-foreground)",
        accent: "var(--accent)",
        "accent-foreground": "var(--accent-foreground)",
        destructive: "var(--destructive)",
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
