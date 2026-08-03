import { useCallback, useEffect, useState } from "react";

/**
 * useTheme：深色/浅色模式（架构 §1.2；默认深色）。
 * - localStorage `market_dashboard_theme` 持久化。
 * - index.css：`:root`/`[class~="dark"]` 为深色 token，`[class~="light"]` 覆盖为浅色。
 *   因此切换 = 在 <html> 上增删 light/dark class。
 */

export const THEME_STORAGE_KEY = "market_dashboard_theme";

export type Theme = "dark" | "light";

function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return "dark";
}

function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);
}

export interface UseThemeResult {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  isDark: boolean;
}

export function useTheme(): UseThemeResult {
  const [theme, setThemeState] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // localStorage 不可用（隐私模式等）时静默降级，主题仍生效于本次会话
    }
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  return { theme, setTheme, toggleTheme, isDark: theme === "dark" };
}
