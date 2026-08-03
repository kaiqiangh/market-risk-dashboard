/**
 * i18n key 完整性测试（PRD §25.2：Translation key 完整性 / 中文缺失 key / 英文缺失 key）。
 * tests/i18n 为 §25.2 完整套件的权威目录（tests/frontend/i18n.test.ts 为 T04 遗留回归）。
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

describe("i18n 命名空间完整性", () => {
  it("只允许 zh-CN / en 两个语言目录", () => {
    const langs = readdirSync(LOCALES_DIR, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
    expect(langs).toEqual(["en", "zh-CN"]);
  });

  it("每个语言都有全部 9 个命名空间文件", () => {
    for (const lang of LANGS) {
      for (const ns of NAMESPACES) {
        const p = path.join(LOCALES_DIR, lang, `${ns}.json`);
        expect(() => readFileSync(p, "utf-8"), `${lang}/${ns}.json 缺失`).not.toThrow();
      }
    }
  });
});

describe("Translation key 完整性", () => {
  for (const ns of NAMESPACES) {
    it(`中文文件缺失 key（en 有而 zh 无）为空: ${ns}`, () => {
      const zh = new Set(flattenKeys(load("zh-CN", ns)));
      const en = new Set(flattenKeys(load("en", ns)));
      const missingInZh = [...en].filter((k) => !zh.has(k));
      expect(missingInZh, `en-only keys in ${ns}`).toEqual([]);
    });

    it(`英文文件缺失 key（zh 有而 en 无）为空: ${ns}`, () => {
      const zh = new Set(flattenKeys(load("zh-CN", ns)));
      const en = new Set(flattenKeys(load("en", ns)));
      const missingInEn = [...zh].filter((k) => !en.has(k));
      expect(missingInEn, `zh-only keys in ${ns}`).toEqual([]);
    });
  }

  it("所有翻译值非空字符串", () => {
    for (const lang of LANGS) {
      for (const ns of NAMESPACES) {
        const obj = load(lang, ns);
        for (const key of flattenKeys(obj)) {
          const value = key.split(".").reduce<unknown>((acc, part) => {
            return (acc as Record<string, unknown>)?.[part];
          }, obj);
          expect(
            typeof value === "string" && value.trim().length > 0,
            `${lang}/${ns}.${key} 为空`,
          ).toBe(true);
        }
      }
    }
  });
});
