import { useCallback, useEffect, useState } from "react";

/**
 * useTheme: tri-state theme preference (ADR-0001; dark-first terminal).
 * - Preference: "dark" | "light" | "system", persisted in localStorage.
 * - Default for first-time visitors is ALWAYS dark, regardless of OS appearance.
 * - "system" is opt-in and is the only mode that follows prefers-color-scheme.
 * - Legacy stored values ("dark"/"light") migrate directly; absence means "dark".
 * - In index.css: `:root`/`[class~="dark"]` are dark tokens, `[class~="light"]` overrides.
 */

export const THEME_STORAGE_KEY = "market_dashboard_theme";

export type ThemePreference = "dark" | "light" | "system";
export type ResolvedTheme = "dark" | "light";

/** Back-compat alias for the pre-tri-state binary Theme type. */
export type Theme = ResolvedTheme;

function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") return "dark";
  let stored: string | null = null;
  try {
    stored = window.localStorage?.getItem(THEME_STORAGE_KEY) ?? null;
  } catch {
    // Some test/private-browser environments expose localStorage without storage access.
  }
  // Legacy binary values migrate directly; anything unrecognized means dark (ADR-0001)
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return "dark";
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(resolved);
}

export interface UseThemeResult {
  /** Stored preference: dark | light | system. */
  preference: ThemePreference;
  /** Effective theme after resolving "system". */
  theme: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  /** Back-compat binary setter (maps to setPreference). */
  setTheme: (theme: ResolvedTheme) => void;
  /** Back-compat dark/light flip for legacy callers (mapped to explicit preferences). */
  toggleTheme: () => void;
  isDark: boolean;
}

export function useTheme(): UseThemeResult {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  const [resolved, setResolved] = useState<ResolvedTheme>(() =>
    preference === "system" ? systemTheme() : preference,
  );

  // Resolve + apply + persist whenever the preference changes
  useEffect(() => {
    const next = preference === "system" ? systemTheme() : preference;
    setResolved(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
      // Silently degrade when localStorage is unavailable (private mode etc.)
    }
  }, [preference]);

  // Only "system" mode listens to OS appearance changes (ADR-0001)
  useEffect(() => {
    if (preference !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      const next = systemTheme();
      setResolved(next);
      applyTheme(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next);
  }, []);

  const setTheme = useCallback((theme: ResolvedTheme) => {
    setPreferenceState(theme);
  }, []);

  const toggleTheme = useCallback(() => {
    setPreferenceState((prev) => {
      const current = prev === "system" ? systemTheme() : prev;
      return current === "dark" ? "light" : "dark";
    });
  }, []);

  return { preference, theme: resolved, setPreference, setTheme, toggleTheme, isDark: resolved === "dark" };
}
