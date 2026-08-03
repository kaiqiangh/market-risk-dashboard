import type { Config } from "tailwindcss";

/**
 * Tailwind 配置。
 * 风险色使用语义 token（CSS 变量），定义在 src/index.css 的 :root 与 .dark。
 * 颜色不是唯一表达，必须配文本 + 图标 + 数值（架构 §8.6）。
 */
const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 语义 token：映射到 src/index.css 中定义的 CSS 变量
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
