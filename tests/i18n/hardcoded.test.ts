/**
 * Hardcoded text detection (PRD §25.2 / §8.10: no hardcoded Chinese or English directly in components).
 * Scans all .ts/.tsx files under src for Chinese string literals (translation calls/imports/comments exempt).
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

describe("hardcoded text detection", () => {
  it("no hardcoded Chinese string literals in src code", () => {
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
