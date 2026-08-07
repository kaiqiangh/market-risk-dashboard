#!/usr/bin/env node
/**
 * Publish secret gate (S-1/#92): fail the run before publish if a configured API key
 * (pattern or literal value) appears anywhere under the published tree or the run logs.
 *
 * Why both patterns AND literals: a pattern catches the shape (`apikey=…`), the literal
 * values catch a key that landed verbatim in a file without its parameter name — which is
 * exactly the FMP/FRED query-param style this repo ships. The env values are read from the
 * local `.env` when it exists (CI has no secrets, so there the literal check is a no-op and
 * only the patterns apply).
 *
 * Usage: node scripts/scan-secrets.mjs [--root <repo>]
 * Exit code: 0 = clean; 1 = a secret-shaped token was found.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = process.argv.includes("--root")
  ? resolve(process.argv[process.argv.indexOf("--root") + 1])
  : resolve(__dirname, "..");

//: Everything that ships to the public site plus the run logs (the two places an
//: exception repr embedding a URL query could land).
const TARGET_DIRS = ["public/data", "artifacts/logs"];

//: Key-shaped tokens: named key parameters, bare 32-hex (FMP/FRED key format), and a
//: generic long-token shape (32-64 alphanumerics).
//: Key-shaped tokens. Only the named-parameter shape is a pattern: this repo's news dedupe
//: ids are sha1 (40 hex) and appear all over the published data, so any bare-token pattern
//: false-positives. FRED/FMP keys always travel as named query parameters (`api_key=`/
//: `apikey=`), which this catches; a key that reached a file without its parameter name is
//: caught by the literal env-value check below — the strong gate for this repo's key style.
const PATTERNS = [
  /(api[_-]?key|apikey|token|secret|password)\s*[:=]\s*[^&\s"'\u4e00-\u9fff]+/i,
];

function envLiterals() {
  const path = join(ROOT, ".env");
  if (!existsSync(path)) return [];
  const out = [];
  for (const line of readFileSync(path, "utf-8").split(/\r?\n/)) {
    const m = /^([A-Za-z0-9_]+)\s*=\s*(.+)$/.exec(line.trim());
    if (!m) continue;
    const [key, value] = [m[1], m[2].trim()];
    if (/(API_KEY|TOKEN|SECRET)/i.test(key) && value && !value.startsWith("#")) {
      out.push(value);
    }
  }
  return out.filter((v) => v.length >= 8);
}

function walk(dir, files = []) {
  if (!existsSync(dir)) return files;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, files);
    else files.push(p);
  }
  return files;
}

const literals = envLiterals();
const hits = [];
let filesScanned = 0;

for (const rel of TARGET_DIRS) {
  const dir = join(ROOT, rel);
  if (!existsSync(dir)) continue;
  for (const file of walk(dir)) {
    filesScanned += 1;
    const text = readFileSync(file, "utf-8");
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      for (const pattern of PATTERNS) {
        const m = pattern.exec(line);
        if (m) {
          hits.push(`${rel}/${file.replace(dir + "/", "")}:${i + 1}: pattern ${pattern}: ${m[0].slice(0, 60)}`);
          break;
        }
      }
      for (const secret of literals) {
        if (secret && line.includes(secret)) {
          hits.push(`${rel}/${file.replace(dir + "/", "")}:${i + 1}: literal env value (masked)`);
          break;
        }
      }
    }
  }
}

console.log(`[scan-secrets] scanned ${filesScanned} files, ${hits.length} hit(s)`);
for (const h of hits) console.log(`  [SECRET] ${h}`);
if (hits.length > 0) {
  console.log("[scan-secrets] result: FAILED — fix before publish");
  process.exit(1);
}
console.log("[scan-secrets] result: PASSED");
