import "@testing-library/jest-dom/vitest";
import { beforeEach } from "vitest";
import i18n from "@/i18n";

if (typeof window !== "undefined" && !window.localStorage) {
  const values = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      clear: () => values.clear(),
      getItem: (key: string) => values.get(key) ?? null,
      key: (index: number) => Array.from(values.keys())[index] ?? null,
      removeItem: (key: string) => values.delete(key),
      setItem: (key: string, value: string) => values.set(key, String(value)),
      get length() {
        return values.size;
      },
    } satisfies Storage,
  });
}

/**
 * Global test setup:
 * - jest-dom matchers
 * - matchMedia stub (jsdom lacks it): OS appearance defaults to dark;
 *   tests control it via `window.__setSystemLight(boolean)` which also
 *   fires change events at registered listeners.
 * - reset i18n language to zh-CN and clear localStorage before each case
 *   (i18n is a module singleton; avoids cross-file leakage)
 */

let systemLight = false;
const mediaListeners = new Set<(event: { matches: boolean }) => void>();

if (typeof window !== "undefined") {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("light") ? systemLight : false,
    media: query,
    onchange: null,
    addEventListener: (_type: string, cb: (event: { matches: boolean }) => void) => mediaListeners.add(cb),
    removeEventListener: (_type: string, cb: (event: { matches: boolean }) => void) => mediaListeners.delete(cb),
    addListener: (cb: (event: { matches: boolean }) => void) => mediaListeners.add(cb),
    removeListener: (cb: (event: { matches: boolean }) => void) => mediaListeners.delete(cb),
    dispatchEvent: () => true,
  })) as unknown as typeof window.matchMedia;

  (window as unknown as { __setSystemLight: (v: boolean) => void }).__setSystemLight = (v: boolean) => {
    systemLight = v;
    mediaListeners.forEach((cb) => cb({ matches: v }));
  };
}

beforeEach(async () => {
  window.localStorage.clear();
  systemLight = false;
  document.documentElement.classList.remove("dark", "light");
  await i18n.changeLanguage("zh-CN");
});
