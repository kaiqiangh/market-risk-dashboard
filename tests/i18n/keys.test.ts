/**
 * i18n key integrity tests (PRD §25.2: translation key integrity / missing keys in zh / missing keys in en).
 * tests/i18n is the authoritative directory for the §25.2 full suite (tests/frontend/i18n.test.ts is the T04 regression leftover).
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOCALES_DIR = path.resolve(__dirname, "../../src/i18n/locales");

const NAMESPACES = [
  "common",
  "dashboard",
  "macro",
  "equities",
  "themes",
  "news",
  "calendar",
  "risk",
  "status",
] as const;

const LANGS = ["zh-CN", "en"] as const;

function load(lang: string, ns: string): Record<string, unknown> {
  const p = path.join(LOCALES_DIR, lang, `${ns}.json`);
  return JSON.parse(readFileSync(p, "utf-8")) as Record<string, unknown>;
}

function flattenKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const keyPath = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      return flattenKeys(v as Record<string, unknown>, keyPath);
    }
    return [keyPath];
  });
}

describe("i18n namespace integrity", () => {
  it("only the zh-CN / en language directories are allowed", () => {
    const langs = readdirSync(LOCALES_DIR, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
    expect(langs).toEqual(["en", "zh-CN"]);
  });

  it("every language has all 9 namespace files", () => {
    for (const lang of LANGS) {
      for (const ns of NAMESPACES) {
        const p = path.join(LOCALES_DIR, lang, `${ns}.json`);
        expect(() => readFileSync(p, "utf-8"), `${lang}/${ns}.json missing`).not.toThrow();
      }
    }
  });
});

describe("Translation key integrity", () => {
  for (const ns of NAMESPACES) {
    it(`no keys missing in Chinese files (en has, zh lacks): ${ns}`, () => {
      const zh = new Set(flattenKeys(load("zh-CN", ns)));
      const en = new Set(flattenKeys(load("en", ns)));
      const missingInZh = [...en].filter((k) => !zh.has(k));
      expect(missingInZh, `en-only keys in ${ns}`).toEqual([]);
    });

    it(`no keys missing in English files (zh has, en lacks): ${ns}`, () => {
      const zh = new Set(flattenKeys(load("zh-CN", ns)));
      const en = new Set(flattenKeys(load("en", ns)));
      const missingInEn = [...zh].filter((k) => !en.has(k));
      expect(missingInEn, `zh-only keys in ${ns}`).toEqual([]);
    });
  }

  it("all translation values are non-empty strings", () => {
    for (const lang of LANGS) {
      for (const ns of NAMESPACES) {
        const obj = load(lang, ns);
        for (const key of flattenKeys(obj)) {
          const value = key.split(".").reduce<unknown>((acc, part) => {
            return (acc as Record<string, unknown>)?.[part];
          }, obj);
          expect(
            typeof value === "string" && value.trim().length > 0,
            `${lang}/${ns}.${key} is empty`,
          ).toBe(true);
        }
      }
    }
  });
});
