/**
 * i18n integrity tests (acceptance 7):
 * 1) Chinese files missing keys (en has, zh lacks)
 * 2) English files missing keys (zh has, en lacks)
 * 3) Hardcoded text detection (Chinese string literals in src code that are not comments or t() calls)
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import zhCommon from "@/i18n/locales/zh-CN/common.json";
import zhDashboard from "@/i18n/locales/zh-CN/dashboard.json";
import zhMacro from "@/i18n/locales/zh-CN/macro.json";
import zhEquities from "@/i18n/locales/zh-CN/equities.json";
import zhThemes from "@/i18n/locales/zh-CN/themes.json";
import zhNews from "@/i18n/locales/zh-CN/news.json";
import zhCalendar from "@/i18n/locales/zh-CN/calendar.json";
import zhRisk from "@/i18n/locales/zh-CN/risk.json";
import zhStatus from "@/i18n/locales/zh-CN/status.json";

import enCommon from "@/i18n/locales/en/common.json";
import enDashboard from "@/i18n/locales/en/dashboard.json";
import enMacro from "@/i18n/locales/en/macro.json";
import enEquities from "@/i18n/locales/en/equities.json";
import enThemes from "@/i18n/locales/en/themes.json";
import enNews from "@/i18n/locales/en/news.json";
import enCalendar from "@/i18n/locales/en/calendar.json";
import enRisk from "@/i18n/locales/en/risk.json";
import enStatus from "@/i18n/locales/en/status.json";

const NS = [
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

const ZH: Record<string, Record<string, unknown>> = {
  common: zhCommon as unknown as Record<string, unknown>,
  dashboard: zhDashboard as unknown as Record<string, unknown>,
  macro: zhMacro as unknown as Record<string, unknown>,
  equities: zhEquities as unknown as Record<string, unknown>,
  themes: zhThemes as unknown as Record<string, unknown>,
  news: zhNews as unknown as Record<string, unknown>,
  calendar: zhCalendar as unknown as Record<string, unknown>,
  risk: zhRisk as unknown as Record<string, unknown>,
  status: zhStatus as unknown as Record<string, unknown>,
};

const EN: Record<string, Record<string, unknown>> = {
  common: enCommon as unknown as Record<string, unknown>,
  dashboard: enDashboard as unknown as Record<string, unknown>,
  macro: enMacro as unknown as Record<string, unknown>,
  equities: enEquities as unknown as Record<string, unknown>,
  themes: enThemes as unknown as Record<string, unknown>,
  news: enNews as unknown as Record<string, unknown>,
  calendar: enCalendar as unknown as Record<string, unknown>,
  risk: enRisk as unknown as Record<string, unknown>,
  status: enStatus as unknown as Record<string, unknown>,
};

function flattenKeys(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const keyPath = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      return flattenKeys(v as Record<string, unknown>, keyPath);
    }
    return [keyPath];
  });
}

describe("i18n key integrity", () => {
  it("all namespace files exist (zh-CN + en, 9 each)", () => {
    for (const ns of NS) {
      expect(ZH[ns], `zh-CN ${ns}`).toBeDefined();
      expect(EN[ns], `en ${ns}`).toBeDefined();
    }
  });

  it("no keys missing in Chinese files (en has, zh lacks)", () => {
    for (const ns of NS) {
      const zhKeys = new Set(flattenKeys(ZH[ns]));
      const enKeys = new Set(flattenKeys(EN[ns]));
      const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
      expect(missingInZh, `en-only keys in ${ns}`).toEqual([]);
    }
  });

  it("no keys missing in English files (zh has, en lacks)", () => {
    for (const ns of NS) {
      const zhKeys = new Set(flattenKeys(ZH[ns]));
      const enKeys = new Set(flattenKeys(EN[ns]));
      const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));
      expect(missingInEn, `zh-only keys in ${ns}`).toEqual([]);
    }
  });
});

describe("hardcoded text detection", () => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const srcDir = path.resolve(__dirname, "../../src");

  /** Allowed files: bilingual formatting vocabulary (format.ts) and asset pool data (config/universe.ts). */
  const ALLOWED_FILES = new Set([
    path.join(srcDir, "lib/format.ts"),
    path.join(srcDir, "config/universe.ts"),
  ]);

  /** Strip comments (block + line comments, whole-file processing, block comments may span lines). */
  function stripComments(code: string): string {
    let out = "";
    let inBlock = false;
    for (let i = 0; i < code.length; i++) {
      if (inBlock) {
        if (code[i] === "*" && code[i + 1] === "/") {
          inBlock = false;
          i += 1;
        }
        continue;
      }
      if (code[i] === "/" && code[i + 1] === "*") {
        inBlock = true;
        i += 1;
        continue;
      }
      if (code[i] === "/" && code[i + 1] === "/") {
        // line comment: skip to end of line
        while (i < code.length && code[i] !== "\n") i += 1;
        continue;
      }
      out += code[i];
    }
    return out;
  }

  function walk(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) return walk(full);
      if (/\.(ts|tsx)$/.test(entry.name)) return [full];
      return [];
    });
  }

  it("no hardcoded Chinese string literals in src code", () => {
    const violations: string[] = [];
    for (const file of walk(srcDir)) {
      if (ALLOWED_FILES.has(file)) continue;
      const code = readFileSync(file, "utf-8");
      const stripped = stripComments(code); // strip comments for the whole file (block comments span lines)
      const lines = stripped.split("\n");
      lines.forEach((line, idx) => {
        // exempt translation calls / i18n-related / import statements
        if (/\bt\(\s*["'`]/.test(line)) return;
        if (/i18n|useTranslation/.test(line)) return;
        if (line.includes("import")) return;
        const stringRe = /(["'`])((?:[^"'`\\]|\\.)*)\1/g;
        let m: RegExpExecArray | null;
        while ((m = stringRe.exec(line)) !== null) {
          if (/[\u4e00-\u9fff]/.test(m[2])) {
            violations.push(`${path.relative(srcDir, file)}:${idx + 1}: ${m[2]}`);
          }
        }
      });
    }
    expect(violations).toEqual([]);
  });
});
