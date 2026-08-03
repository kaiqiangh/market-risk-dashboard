/**
 * i18n 完整性测试（验收 7）：
 * 1) 中文文件缺失 key（en 有而 zh 无）
 * 2) 英文文件缺失 key（zh 有而 en 无）
 * 3) 硬编码文本检测（src 代码中非注释、非翻译调用的中文字符串字面量）
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

describe("i18n key 完整性", () => {
  it("命名空间文件齐全（zh-CN + en 各 9 个）", () => {
    for (const ns of NS) {
      expect(ZH[ns], `zh-CN ${ns}`).toBeDefined();
      expect(EN[ns], `en ${ns}`).toBeDefined();
    }
  });

  it("中文文件缺失 key（en 有而 zh 无）为空", () => {
    for (const ns of NS) {
      const zhKeys = new Set(flattenKeys(ZH[ns]));
      const enKeys = new Set(flattenKeys(EN[ns]));
      const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
      expect(missingInZh, `en-only keys in ${ns}`).toEqual([]);
    }
  });

  it("英文文件缺失 key（zh 有而 en 无）为空", () => {
    for (const ns of NS) {
      const zhKeys = new Set(flattenKeys(ZH[ns]));
      const enKeys = new Set(flattenKeys(EN[ns]));
      const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));
      expect(missingInEn, `zh-only keys in ${ns}`).toEqual([]);
    }
  });
});

describe("硬编码文本检测", () => {
  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const srcDir = path.resolve(__dirname, "../../src");

  /** 允许文件：双语格式化词汇（format.ts）与资产池数据（config/universe.ts）。 */
  const ALLOWED_FILES = new Set([
    path.join(srcDir, "lib/format.ts"),
    path.join(srcDir, "config/universe.ts"),
  ]);

  /** 去注释（块注释 + 行注释，整文件处理，块注释跨行）。 */
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
        // 行注释：跳到行尾
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

  it("src 代码中无硬编码中文字符串字面量", () => {
    const violations: string[] = [];
    for (const file of walk(srcDir)) {
      if (ALLOWED_FILES.has(file)) continue;
      const code = readFileSync(file, "utf-8");
      const stripped = stripComments(code); // 整文件去注释（块注释跨行）
      const lines = stripped.split("\n");
      lines.forEach((line, idx) => {
        // 翻译调用 / i18n 相关 / import 语句豁免
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
