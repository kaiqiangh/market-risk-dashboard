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
// FreshnessStatus enum (#74 QA note): this is a zero-dependency script, so it cannot
// import the canonical definitions — keep this set in sync with
// src/schemas/envelope.ts (Zod `FreshnessStatus`) and pipeline/schemas/envelope.py
// (`FreshnessStatus = Literal[...]`). The values are identical in all three homes.
const FRESHNESS = new Set(["fresh", "delayed", "stale", "missing", "degraded"]);
const ENVELOPE_FILES = new Set([
  "macro.json", "equities.json", "sectors.json", "crypto.json",
  "news.json", "calendar.json", "risk.json", "dashboard.json",
]);
const STANDALONE_FILES = new Set(["facts.json", "analysis.zh-CN.json", "analysis.en.json"]);

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
    if (ENVELOPE_FILES.has(name)) {
      checkEnvelope(name, data);
      if (name === "risk.json") checkRiskRanges(name, data);
    } else if (STANDALONE_FILES.has(name)) {
      if (typeof data.schema_version !== "string") errors.push(`${name}: missing schema_version`);
      if (name.startsWith("analysis.")) {
        const lang = name.slice("analysis.".length, -".json".length);
        if (!["zh-CN", "en"].includes(lang)) errors.push(`${name}: unknown language key ${lang}`);
        if (data.language !== lang) errors.push(`${name}: language field does not match filename`);
      }
    } else {
      warnings.push(`${name}: unregistered dataset file (unknown schema)`);
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

checkLatest();
checkNewsDuplicates();
checkHistory();

console.log(`[validate-json] checked ${filesChecked} files, ${errors.length} ERROR(s), ${warnings.length} WARNING(s)`);
for (const e of errors) console.log(`  [ERROR] ${e}`);
for (const w of warnings) console.log(`  [WARN ] ${w}`);

if (errors.length > 0) {
  console.log("[validate-json] result: FAILED");
  process.exit(1);
}
console.log("[validate-json] result: PASSED");
process.exit(0);
