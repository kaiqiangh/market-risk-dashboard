import type { Config } from "tailwindcss";

/**
 * Tailwind configuration.
 * Risk colors use semantic tokens (CSS variables), defined in src/index.css under :root and .dark.
 * Color is not the only expression; always pair with text + icon + value (architecture §8.6).
 */
const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic tokens: map to the CSS variables defined in src/index.css
        risk: {
          low: "var(--risk-low)",
          caution: "var(--risk-caution)",
          high: "var(--risk-high)",
          severe: "var(--risk-severe)",
          na: "var(--risk-na)",
        },
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
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
