/**
 * useTheme tri-state tests (ADR-0001, spec #23 ticket #26).
 * Covers: dark default for first-time visitors (even with a light OS),
 * explicit preferences, system mode following the OS (and reacting to OS
 * changes), non-system modes ignoring the OS, and legacy localStorage migration.
 */
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { THEME_STORAGE_KEY, useTheme } from "@/hooks/useTheme";

function setSystemLight(v: boolean) {
  act(() => {
    (window as unknown as { __setSystemLight: (v: boolean) => void }).__setSystemLight(v);
  });
}

beforeEach(() => {
  setSystemLight(false);
});

describe("useTheme", () => {
  it("defaults to dark for first-time visitors, even when the OS is light", () => {
    setSystemLight(true);
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("dark");
    expect(result.current.theme).toBe("dark");
    expect(result.current.isDark).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("migrates legacy binary stored values directly", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("light");
    expect(result.current.theme).toBe("light");
  });

  it("treats an unrecognized stored value as dark (not system)", () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, "purple");
    const { result } = renderHook(() => useTheme());
    expect(result.current.preference).toBe("dark");
  });

  it("persists explicit preference changes", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("light"));
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    act(() => result.current.setPreference("dark"));
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("system mode resolves from the OS and reacts to OS changes", () => {
    setSystemLight(true);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("system"));
    expect(result.current.theme).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);

    setSystemLight(false);
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("explicit dark/light modes ignore OS changes", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setPreference("light"));
    setSystemLight(false);
    expect(result.current.theme).toBe("light");

    act(() => result.current.setPreference("dark"));
    setSystemLight(true);
    expect(result.current.theme).toBe("dark");
  });

  it("back-compat toggleTheme flips between explicit dark and light", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggleTheme());
    expect(result.current.preference).toBe("light");
    act(() => result.current.toggleTheme());
    expect(result.current.preference).toBe("dark");
  });
});
