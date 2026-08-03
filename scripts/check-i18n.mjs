#!/usr/bin/env node
/**
 * i18n translation file validation (the "Check translation files" step in deploy-pages.yml, zero dependencies).
 * Checks:
 * 1. All namespace files present (9 each for zh-CN and en).
 * 2. No unknown language directories (only zh-CN / en allowed).
 * 3. Keys missing from the Chinese files (present in en but not zh).
 * 4. Keys missing from the English files (present in zh but not en).
 *
 * Usage: node scripts/check-i18n.mjs
 * Exit code: 0 = pass; 1 = missing keys.
 */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCALES = resolve(__dirname, "..", "src", "i18n", "locales");
const NAMESPACES = [
  "common", "dashboard", "macro", "equities", "themes", "news", "calendar", "risk", "status",
];

const errors = [];

function flattenKeys(obj, prefix = "") {
  return Object.entries(obj).flatMap(([k, v]) => {
    const keyPath = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      return flattenKeys(v, keyPath);
    }
    return [keyPath];
  });
}

function loadNamespace(lang, ns) {
  const p = join(LOCALES, lang, `${ns}.json`);
  if (!existsSync(p)) return null;
  try {
    return JSON.parse(readFileSync(p, "utf-8"));
  } catch (e) {
    errors.push(`${lang}/${ns}.json: cannot parse JSON: ${e.message}`);
    return null;
  }
}

// 1) Unknown language directories
const langs = readdirSync(LOCALES, { withFileTypes: true })
  .filter((e) => e.isDirectory())
  .map((e) => e.name);
for (const lang of langs) {
  if (lang !== "zh-CN" && lang !== "en") {
    errors.push(`unknown language directory: ${lang} (only zh-CN / en allowed)`);
  }
}

// 2) All namespaces present
for (const lang of ["zh-CN", "en"]) {
  for (const ns of NAMESPACES) {
    if (!existsSync(join(LOCALES, lang, `${ns}.json`))) {
      errors.push(`${lang}/${ns}.json missing`);
    }
  }
}

// 3/4) Key completeness (both directions)
for (const ns of NAMESPACES) {
  const zh = loadNamespace("zh-CN", ns);
  const en = loadNamespace("en", ns);
  if (zh === null || en === null) continue;
  const zhKeys = new Set(flattenKeys(zh));
  const enKeys = new Set(flattenKeys(en));
  const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
  const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));
  if (missingInZh.length > 0) errors.push(`${ns}: keys missing in Chinese (present in en but not zh): ${missingInZh.join(", ")}`);
  if (missingInEn.length > 0) errors.push(`${ns}: keys missing in English (present in zh but not en): ${missingInEn.join(", ")}`);
}

if (errors.length > 0) {
  console.log("[check-i18n] FAILED:");
  for (const e of errors) console.log(`  - ${e}`);
  process.exit(1);
}
console.log(`[check-i18n] PASSED: all ${NAMESPACES.length} namespaces complete for zh-CN/en`);
process.exit(0);
