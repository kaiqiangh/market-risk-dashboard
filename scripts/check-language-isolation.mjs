#!/usr/bin/env node
/**
 * Static language-isolation gate for locale values.
 * Machine identifiers and rendered-value placeholders are allowed; human-readable
 * prose must not contain the other locale's alphabet.
 */
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const LOCALES = join(ROOT, "src", "i18n", "locales");
const NAMESPACES = ["common", "dashboard", "macro", "equities", "themes", "news", "calendar", "risk", "status"];
const MACHINE_TOKENS = JSON.parse(readFileSync(join(ROOT, "src", "lib", "machineTokens.json"), "utf8"));
const MACHINE_PATTERN = new RegExp(`\\b(?:${MACHINE_TOKENS.join("|")})\\b`, "gi");
const CJK_PATTERN = /[\u3400-\u9fff]/u;
const LATIN_PATTERN = /[A-Za-z]/u;

function flattenValues(value, path = "") {
  if (typeof value === "string") return [[path, value]];
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).flatMap(([key, child]) => flattenValues(child, path ? `${path}.${key}` : key));
}

function isSafe(value, lang) {
  const stripped = value.replace(/\{\{[^}]+\}\}/g, " ").replace(MACHINE_PATTERN, " ");
  return lang === "zh-CN" ? !LATIN_PATTERN.test(stripped) : !CJK_PATTERN.test(stripped);
}

const errors = [];
for (const lang of ["zh-CN", "en"]) {
  for (const namespace of NAMESPACES) {
    const file = join(LOCALES, lang, `${namespace}.json`);
    const data = JSON.parse(readFileSync(file, "utf8"));
    for (const [path, value] of flattenValues(data)) {
      if (!isSafe(value, lang)) errors.push(`${lang}/${namespace}.${path}: ${JSON.stringify(value)}`);
    }
  }
}

if (errors.length > 0) {
  console.error("[check-language-isolation] FAILED:");
  for (const error of errors) console.error(`  - ${error}`);
  process.exit(1);
}
console.log("[check-language-isolation] PASSED: locale prose is isolated; machine-token policy is enforced");
