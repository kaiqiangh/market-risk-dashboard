#!/usr/bin/env node
/**
 * Node structural data validation (the "Validate JSON Schema" step in deploy-pages.yml, zero dependencies).
 * Covers: JSON parseability (JS JSON.parse natively rejects NaN/Infinity), envelope required fields,
 * ISO 8601 UTC timestamps, freshness enum, data_quality range, risk score ranges,
 * duplicate news ids, history slice row structure.
 *
 * Full validation (including Pydantic Schema + AI bilingual consistency) lives in pipeline/validation/ci_checks.py,
 * executed by validate-data.yml / scripts/validate_data.sh. This script is the lightweight gate for frontend CI.
 *
 * Usage: node scripts/validate-json.mjs [--data-dir public/data]
 */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const DATA_DIR = process.argv.includes("--data-dir")
  ? resolve(process.argv[process.argv.indexOf("--data-dir") + 1])
  : join(ROOT, "public", "data");

const errors = [];
const warnings = [];
let filesChecked = 0;

const ISO_UTC_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Contract vocabularies and the dataset registry, generated from pipeline/schemas/ by
 * scripts/gen_ts_contracts.py (#101). This script used to keep its own copy of the
 * freshness enum and its own list of dataset filenames "in sync by hand"; both fell
 * behind. The enum never learned about `empty`, and news.zh-translations.json was
 * reported as an unregistered file on every run. Reading the generated JSON keeps the
 * script zero-dependency while removing the third home for the same facts.
 */
const CONTRACTS = JSON.parse(
  readFileSync(join(ROOT, "src", "schemas", "generated", "constants.json"), "utf-8"),
);
const FRESHNESS = new Set(CONTRACTS.freshness_status);
const REASON_CODES = new Set(CONTRACTS.reason_codes);
const CANONICAL_KEYS = CONTRACTS.canonical_dataset_keys;

/** filename → dataset spec, for every published file. */
const SPEC_BY_FILENAME = new Map();
for (const [key, spec] of Object.entries(CONTRACTS.datasets)) {
  for (const filename of spec.filenames) {
    SPEC_BY_FILENAME.set(filename, { key, ...spec });
  }
}

function loadJson(rel) {
  const p = join(DATA_DIR, rel);
  if (!existsSync(p)) return null;
  // JSON.parse throws SyntaxError on NaN/Infinity (JS rejects illegal constants by default)
  return JSON.parse(readFileSync(p, "utf-8"));
}

function checkLatest() {
  const latestDir = join(DATA_DIR, "latest");
  if (!existsSync(latestDir)) {
    errors.push("latest directory missing");
    return;
  }
  for (const name of readdirSync(latestDir).filter((f) => f.endsWith(".json"))) {
    const p = join(latestDir, name);
    let data;
    try {
      data = JSON.parse(readFileSync(p, "utf-8"));
      filesChecked += 1;
    } catch (e) {
      errors.push(`${name}: cannot parse JSON (contains NaN/Infinity?): ${e.message}`);
      continue;
    }
    const spec = SPEC_BY_FILENAME.get(name);
    if (!spec) {
      warnings.push(`${name}: unregistered dataset file (unknown schema)`);
      continue;
    }
    if (spec.enveloped) {
      checkEnvelope(name, data);
      if (name === "risk.json") checkRiskRanges(name, data);
    } else {
      if (spec.has_schema_version && typeof data.schema_version !== "string") {
        errors.push(`${name}: missing schema_version`);
      }
      if (name.startsWith("analysis.")) {
        const lang = name.slice("analysis.".length, -".json".length);
        if (!["zh-CN", "en"].includes(lang)) errors.push(`${name}: unknown language key ${lang}`);
        if (data.language !== lang) errors.push(`${name}: language field does not match filename`);
      }
    }
  }
}

function checkEnvelope(name, data) {
  if (typeof data.schema_version !== "string") errors.push(`${name}: missing schema_version`);
  if (typeof data.generated_at !== "string" || !ISO_UTC_RE.test(data.generated_at)) {
    errors.push(`${name}: generated_at is not ISO 8601 UTC: ${data.generated_at}`);
  }
  if (data.source_updated_at != null && (typeof data.source_updated_at !== "string" || !ISO_UTC_RE.test(data.source_updated_at))) {
    errors.push(`${name}: source_updated_at is not ISO 8601 UTC`);
  }
  if (!FRESHNESS.has(data.freshness_status)) {
    errors.push(`${name}: invalid freshness_status: ${data.freshness_status}`);
  }
  const dq = Number(data.data_quality);
  if (!Number.isFinite(dq) || dq < 0 || dq > 1) {
    errors.push(`${name}: data_quality out of range [0,1]: ${data.data_quality}`);
  }
}

function checkRiskRanges(name, data) {
  const payload = data.payload || {};
  const total = Number(payload.total_score);
  if (!Number.isFinite(total) || total < 0 || total > 100) {
    errors.push(`${name}: total_score out of range [0,100]: ${payload.total_score}`);
  }
  for (const dim of payload.dimensions || []) {
    const score = Number(dim.score);
    if (!Number.isFinite(score) || score < 0 || score > 100) {
      errors.push(`${name}: dimension ${dim.key} score out of range [0,100]: ${dim.score}`);
    }
    for (const ind of dim.indicators || []) {
      if (ind.risk_score != null) {
        const rs = Number(ind.risk_score);
        if (!Number.isFinite(rs) || rs < 0 || rs > 100) {
          errors.push(`${name}: indicator ${ind.key} risk_score out of range [0,100]: ${ind.risk_score}`);
        }
      }
    }
  }
  if (payload.confidence != null) {
    const c = Number(payload.confidence);
    if (!Number.isFinite(c) || c < 0 || c > 1) errors.push(`${name}: confidence out of range [0,1]`);
  }
}

function checkNewsDuplicates() {
  const news = loadJson("latest/news.json");
  if (!news) return;
  const items = news.payload?.items || [];
  const ids = new Map();
  const sigs = new Map();
  for (const item of items) {
    if (item.id) ids.set(item.id, (ids.get(item.id) || 0) + 1);
    const sig = `${String(item.title || "").trim().toLowerCase()}|${String(item.source || "").trim().toLowerCase()}|${String(item.published_at || "").trim()}`;
    sigs.set(sig, (sigs.get(sig) || 0) + 1);
  }
  for (const [id, n] of ids) if (n > 1) errors.push(`news.json: duplicate news id ${id} (${n} times)`);
  for (const [sig, n] of sigs) if (n > 1) errors.push(`news.json: duplicate news (title+source+published_at) (${n} times)`);
}

function checkHistory() {
  for (const series of ["risk", "market"]) {
    for (const slice of ["30d", "90d", "daily"]) {
      const rel = `history/${series}/${slice}.json`;
      const rows = loadJson(rel);
      if (!rows) {
        warnings.push(`${rel} missing`);
        continue;
      }
      filesChecked += 1;
      if (!Array.isArray(rows)) {
        errors.push(`${rel}: top level should be an array`);
        continue;
      }
      for (const row of rows) {
        if (!row || typeof row !== "object") {
          errors.push(`${rel}: row is not an object`);
          continue;
        }
        if (!DATE_RE.test(String(row.date || ""))) errors.push(`${rel}: invalid row date: ${row.date}`);
        if (row.total_score != null) {
          const s = Number(row.total_score);
          if (!Number.isFinite(s) || s < 0 || s > 100) errors.push(`${rel}: total_score out of range [0,100]`);
        }
      }
    }
  }
}

/**
 * metadata/freshness.json and metadata/sources.json (#89, #101).
 *
 * These two files are projections of one run record, and the reason a dataset can be
 * `fresh` in one and `degraded` in the other is that nothing ever checked them. The
 * structured reason is the point of #89: a free-text reason let eight datasets publish
 * the literal word "degraded" as their explanation.
 */
function checkFreshnessReason(where, reason) {
  if (!reason || typeof reason !== "object" || Array.isArray(reason)) {
    errors.push(`${where}: reason must be an object {code, detail}`);
    return;
  }
  if (!REASON_CODES.has(reason.code)) {
    errors.push(`${where}: unknown reason code: ${reason.code}`);
  }
  if (reason.detail != null && typeof reason.detail !== "string") {
    errors.push(`${where}: reason.detail must be a string`);
  }
}

function checkMetadata() {
  const freshness = loadJson("metadata/freshness.json");
  const datasets = (freshness && freshness.datasets) || {};
  if (!freshness) {
    warnings.push("metadata/freshness.json missing");
  } else {
    filesChecked += 1;
    for (const key of CANONICAL_KEYS) {
      if (!(key in datasets)) {
        // Every registered dataset reports on every run, including the failed ones —
        // an absent key used to read as "healthy, nothing to report".
        errors.push(`metadata/freshness.json: registered dataset ${key} has no entry`);
      }
    }
    for (const [key, entry] of Object.entries(datasets)) {
      const where = `metadata/freshness.json[${key}]`;
      if (!CANONICAL_KEYS.includes(key)) {
        errors.push(`${where}: not a registered dataset key`);
      }
      if (!FRESHNESS.has(entry?.status)) {
        errors.push(`${where}: invalid status: ${entry?.status}`);
      }
      checkFreshnessReason(where, entry?.reason);
    }
  }

  const sources = loadJson("metadata/sources.json");
  if (!sources) {
    warnings.push("metadata/sources.json missing");
    return;
  }
  filesChecked += 1;
  for (const [domain, entry] of Object.entries(sources.domains || {})) {
    const where = `metadata/sources.json[${domain}]`;
    if (!FRESHNESS.has(entry?.status)) errors.push(`${where}: invalid status: ${entry?.status}`);
    if (typeof entry?.degraded !== "boolean") errors.push(`${where}: degraded must be a boolean`);
    checkFreshnessReason(where, entry?.reason);
    // The contradiction #89 was written to make impossible: a domain cannot be flagged
    // degraded while claiming a healthy status, or vice versa.
    const healthy = entry?.status === "fresh";
    if (healthy && entry?.degraded === true) {
      errors.push(`${where}: status is fresh but degraded is true`);
    }
  }

  // #89/#101: both files are projections of one run record, so a domain's `degraded` must
  // exactly match whether any dataset it serves is degraded in freshness.json. Mirrors
  // pipeline/storage/outcomes.py (the sole renderer): a domain is degraded iff any of its
  // datasets is degraded/missing/stale. Before this check, calendar could be `fresh` in one
  // file and `degraded` in the other.
  if (freshness && sources) {
    const UNHEALTHY = new Set(["degraded", "missing", "stale"]);
    for (const [domain, entry] of Object.entries(sources.domains || {})) {
      const keys = Array.isArray(entry?.datasets) ? entry.datasets : [];
      for (const key of keys) {
        if (!CANONICAL_KEYS.includes(key)) {
          errors.push(`metadata/sources.json[${domain}].datasets: ${key} is not a registered dataset key`);
        }
      }
      if (typeof entry?.degraded !== "boolean") continue;
      const expected = keys.some((k) => UNHEALTHY.has(datasets[k]?.status));
      if (entry.degraded !== expected) {
        errors.push(
          `metadata/sources.json[${domain}]: degraded ${entry.degraded} disagrees with freshness.json (expected ${expected})`,
        );
      }
    }
  }
}

checkLatest();
checkNewsDuplicates();
checkHistory();
checkMetadata();

console.log(`[validate-json] checked ${filesChecked} files, ${errors.length} ERROR(s), ${warnings.length} WARNING(s)`);
for (const e of errors) console.log(`  [ERROR] ${e}`);
for (const w of warnings) console.log(`  [WARN ] ${w}`);

if (errors.length > 0) {
  console.log("[validate-json] result: FAILED");
  process.exit(1);
}
console.log("[validate-json] result: PASSED");
process.exit(0);
