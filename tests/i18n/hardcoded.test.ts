/**
 * 硬编码文本检测（PRD §25.2 / §8.10：不允许直接在组件中硬编码中文或英文）。
 * 扫描 src 下所有 .ts/.tsx 文件中的中文字符串字面量（翻译调用/import/注释豁免）。
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

describe("硬编码文本检测", () => {
  it("src 代码中无硬编码中文字符串字面量", () => {
    const violations: string[] = [];
    for (const file of walk(srcDir)) {
      if (ALLOWED_FILES.has(file)) continue;
      const code = readFileSync(file, "utf-8");
      const stripped = stripComments(code);
      const lines = stripped.split("\n");
      lines.forEach((line, idx) => {
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
