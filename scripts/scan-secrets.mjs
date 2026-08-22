#!/usr/bin/env node
/**
 * Publish secret gate (S-1/#92): fail the run before publish if a configured API key
 * (pattern or literal value) appears anywhere in the repo’s tracked files, the published
 * inputs, or the run logs.
 *
 * Why both patterns AND literals: a pattern catches the shape (`apikey=…`), the literal
 * values catch a key that landed verbatim in a file without its parameter name — which is
 * exactly the FMP/FRED query-param style this repo ships. The env values are read from the
 * local `.env` when it exists (CI has no secrets, so there the literal check is a no-op and
 * only the patterns apply).
 *
 * Coverage (#189): every git-TRACKED file is scanned (the old dir-list scan left tracked
 * non-target files unscanned and made the CI literal check a documented no-op), plus
 * artifacts/logs which are deliberately untracked. dist/ keeps its stricter pattern tier:
 * minified bundle code false-positives on ordinary property names. Binary or oversized
 * files are skipped with a note rather than crashing the gate.
 *
 * Usage: node scripts/scan-secrets.mjs [--root <repo>]
 * Exit code: 0 = clean; 1 = a secret-shaped token was found.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = process.argv.includes("--root")
  ? resolve(process.argv[process.argv.indexOf("--root") + 1])
  : resolve(__dirname, "..");

//: Key-shaped tokens. Only the named-parameter shape is a pattern: this repo’s news dedupe
//: ids are sha1 (40 hex) and appear all over the published data, so any bare-token pattern
//: false-positives. FRED/FMP keys always travel as named query parameters (`api_key=`/
//: `apikey=`), which this catches; a key that reached a file without its parameter name is
//: caught by the literal env-value check below — the strong gate for this repo’s key style.
const PATTERNS = [
  /(api[_-]?key|apikey|token|secret|password)\s*[:=]\s*[^&\s"'\u4e00-\u9fff]+/i,
];

// Bundled application code contains ordinary property names such as `password: true`
// and library identifiers such as `Token=function`. Keep the broad data/log pattern,
// but require a plausible secret value when scanning minified build output.
const DIST_PATTERNS = [
  /(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token)\s*[:=]\s*["']?[A-Za-z0-9._~+/=-]{16,}/i,
  /(?:secret|password)\s*[:=]\s*["'][^"']{8,}["']/i,
];

//: Untracked-but-scanned locations (#189 review): dist/ is gitignored, so it NEVER
//: appears in git ls-files - it must be walked explicitly or the built-bundle surface
//: loses all coverage while the header claims it is guarded. Run logs embed exception
//: reprs (the #92 leak path) and are likewise untracked by design.
const UNTRACKED_SCANS = [
  { dir: "dist", tier: DIST_PATTERNS },
  { dir: "artifacts/logs", tier: PATTERNS },
];


//: Source-tier patterns (#189): ordinary CODE assigns things to variables NAMED api_key
//: all day (settings fields, getattr fallbacks), so the broad named-parameter pattern
//: would fire on every provider module. What distinguishes a leak in source is a
//: plausible KEY VALUE: a long hex literal (or a bare CG- token) on the right side.
const SOURCE_PATTERNS = [
  /(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token)\s*[:=]\s*["']?[0-9a-fA-F]{24,}\b/,
  /\bCG-[A-Za-z0-9]{16,}\b/,
];

//: tests/ holds SYNTHETIC keys shaped exactly like real ones on purpose - pattern hits
//: there are false positives by construction. A real key pasted into a test is still
//: caught by the literal check, which scans every tier.
const LITERAL_ONLY_PREFIXES = ["tests/", "test_"];

//: Max bytes scanned per file; anything larger is build/vendor output where a hit would
//: be noise anyway. Decode-failing files are binary, not a leak channel.
const MAX_FILE_BYTES = 2 * 1024 * 1024;

function stripQuotes(value) {
  // .env values may be wrapped in single or double quotes (#189): the raw QUOTED text
  // never appears in an emitted URL, so the UNQUOTED value is what must be scanned for.
  const m = /^"(.*)"$|^'(.*)'$/.exec(value);
  return m ? (m[1] ?? m[2]) : value;
}

function envLiterals() {
  const path = join(ROOT, ".env");
  if (!existsSync(path)) return [];
  const out = [];
  for (const line of readFileSync(path, "utf-8").split(/\r?\n/)) {
    const m = /^([A-Za-z0-9_]+)\s*=\s*(.+)$/.exec(line.trim());
    if (!m) continue;
    const key = m[1];
    const value = stripQuotes(m[2].trim());
    if (!/(API_KEY|TOKEN|SECRET)/i.test(key)) continue;
    if (!value || value.startsWith("#") || value.length < 8) continue;
    out.push(value);
  }
  return out;
}

//: A key can also travel percent-encoded inside a URL (#189): match both forms.
function literalVariants(secret) {
  try {
    const encoded = encodeURIComponent(secret);
    return encoded === secret ? [secret] : [secret, encoded];
  } catch {
    return [secret];
  }
}

function walk(dir, files = []) {
  if (!existsSync(dir)) return files;
  // withFileTypes + explicit isDirectory(): symlinked directories are NOT followed
  // (#189), so a cycle or an escape into a huge external tree cannot hang the gate.
  const entries = readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.isDirectory()) walk(join(dir, entry.name), files);
  }
  for (const entry of entries) {
    if (entry.isFile()) files.push(join(dir, entry.name));
  }
  return files;
}

function trackedFiles() {
  // Every git-tracked file is publish surface (#189). A gate that cannot enumerate
  // its input must FAIL CLOSED (#189 review): silently scanning only the untracked
  // dirs and printing PASSED would be the worst failure mode a publish gate can have.
  try {
    const out = execFileSync("git", ["ls-files", "-z"], {
      cwd: ROOT,
      encoding: "utf-8",
      maxBuffer: 64 * 1024 * 1024, // monorepo-scale path lists exceed the 1MB default
    });
    return out.split("\u0000").filter(Boolean).map((rel) => resolve(ROOT, rel));
  } catch (err) {
    console.error("[scan-secrets] FATAL: cannot enumerate tracked files:", err.message);
    console.error("[scan-secrets] refusing to report PASSED without a file inventory");
    process.exit(1);
  }
}

const literals = envLiterals().flatMap(literalVariants);
const hits = [];
let filesScanned = 0;
let filesSkipped = 0;

function scanFile(file, tierPatterns, label) {
  let stat;
  try {
    stat = statSync(file);
  } catch {
    return; // vanished mid-scan
  }
  if (!stat.isFile() || stat.size > MAX_FILE_BYTES) {
    filesSkipped += 1;
    return;
  }
  let text;
  try {
    text = readFileSync(file, "utf-8");
  } catch {
    filesSkipped += 1; // binary / non-UTF-8: not a leak channel
    return;
  }
  filesScanned += 1;
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    for (const pattern of tierPatterns) {
      const m = pattern.exec(line);
      if (m) {
        hits.push(`${label}:${i + 1}: pattern match: ${m[0].slice(0, 60)}`);
        break;
      }
    }
    for (const secret of literals) {
      if (line.includes(secret)) {
        hits.push(`${label}:${i + 1}: literal env value (masked)`);
        break;
      }
    }
  }
}

//: Tier assignment (#189): published data gets the broad pattern set (that is where
//: exception reprs land), tests get literals only, every other TRACKED file gets the
//: source tier. The untracked surfaces are walked separately below.
function tierFor(rel) {
  if (rel.startsWith("public/data")) return PATTERNS;
  return SOURCE_PATTERNS;
}

for (const file of trackedFiles()) {
  const rel = relative(ROOT, file);
  const literalOnly = LITERAL_ONLY_PREFIXES.some(
    (prefix) => rel === prefix || rel.startsWith(prefix),
  );
  const tier = literalOnly ? [] : tierFor(rel);
  scanFile(file, tier, rel);
}
for (const { dir: rel, tier } of UNTRACKED_SCANS) {
  const dir = join(ROOT, rel);
  if (!existsSync(dir)) continue;
  for (const file of walk(dir)) {
    scanFile(file, tier, rel + "/" + relative(join(ROOT, rel), file));
  }
}

console.log(`[scan-secrets] scanned ${filesScanned} files (${filesSkipped} skipped), ${hits.length} hit(s)`);
for (const h of hits) console.log(`  [SECRET] ${h}`);
if (hits.length > 0) {
  console.log("[scan-secrets] result: FAILED — fix before publish");
  process.exit(1);
}
console.log("[scan-secrets] result: PASSED");