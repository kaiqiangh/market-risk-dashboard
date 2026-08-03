import { useCallback, useEffect, useState } from "react";

/**
 * useTheme: dark/light mode (architecture §1.2; dark by default).
 * - Persisted in localStorage `market_dashboard_theme`.
 * - In index.css: `:root`/`[class~="dark"]` are dark tokens, `[class~="light"]` overrides to light.
 *   So toggling = adding/removing the light/dark class on <html>.
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
      // Silently degrade when localStorage is unavailable (private mode etc.); the theme still applies for this session
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
