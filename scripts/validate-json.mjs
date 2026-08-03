#!/usr/bin/env node
/**
 * Node 结构数据校验（deploy-pages.yml「校验 JSON Schema」步骤，零依赖）。
 * 覆盖：JSON 可解析（JS JSON.parse 天然拒绝 NaN/Infinity）、envelope 必填字段、
 * 时间戳 ISO 8601 UTC、freshness 枚举、data_quality 范围、风险分数范围、
 * 重复新闻 id、历史切片行结构。
 *
 * 完整校验（含 Pydantic Schema + AI 双语一致性）见 pipeline/validation/ci_checks.py，
 * 由 validate-data.yml / scripts/validate_data.sh 执行。本脚本是前端 CI 的轻量门槛。
 *
 * 用法：node scripts/validate-json.mjs [--data-dir public/data]
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
const FRESHNESS = new Set(["fresh", "delayed", "stale", "missing", "degraded"]);
const ENVELOPE_FILES = new Set([
  "macro.json", "equities.json", "sectors.json", "crypto.json",
  "news.json", "calendar.json", "risk.json",
]);
const STANDALONE_FILES = new Set(["facts.json", "analysis.zh-CN.json", "analysis.en.json"]);

function loadJson(rel) {
  const p = join(DATA_DIR, rel);
  if (!existsSync(p)) return null;
  // JSON.parse 对 NaN/Infinity 抛 SyntaxError（JS 默认拒绝非法常量）
  return JSON.parse(readFileSync(p, "utf-8"));
}

function checkLatest() {
  const latestDir = join(DATA_DIR, "latest");
  if (!existsSync(latestDir)) {
    errors.push("latest 目录缺失");
    return;
  }
  for (const name of readdirSync(latestDir).filter((f) => f.endsWith(".json"))) {
    const p = join(latestDir, name);
    let data;
    try {
      data = JSON.parse(readFileSync(p, "utf-8"));
      filesChecked += 1;
    } catch (e) {
      errors.push(`${name}: 无法解析 JSON（含 NaN/Infinity?）: ${e.message}`);
      continue;
    }
    if (ENVELOPE_FILES.has(name)) {
      checkEnvelope(name, data);
      if (name === "risk.json") checkRiskRanges(name, data);
    } else if (STANDALONE_FILES.has(name)) {
      if (typeof data.schema_version !== "string") errors.push(`${name}: 缺 schema_version`);
      if (name.startsWith("analysis.")) {
        const lang = name.slice("analysis.".length, -".json".length);
        if (!["zh-CN", "en"].includes(lang)) errors.push(`${name}: 未知语言 key ${lang}`);
        if (data.language !== lang) errors.push(`${name}: language 字段与文件名不一致`);
      }
    } else if (name !== "dashboard.json") {
      warnings.push(`${name}: 未注册的数据集文件（未知 schema）`);
    }
  }
}

function checkEnvelope(name, data) {
  if (typeof data.schema_version !== "string") errors.push(`${name}: 缺 schema_version`);
  if (typeof data.generated_at !== "string" || !ISO_UTC_RE.test(data.generated_at)) {
    errors.push(`${name}: generated_at 非 ISO 8601 UTC: ${data.generated_at}`);
  }
  if (data.source_updated_at != null && (typeof data.source_updated_at !== "string" || !ISO_UTC_RE.test(data.source_updated_at))) {
    errors.push(`${name}: source_updated_at 非 ISO 8601 UTC`);
  }
  if (!FRESHNESS.has(data.freshness_status)) {
    errors.push(`${name}: freshness_status 非法: ${data.freshness_status}`);
  }
  const dq = Number(data.data_quality);
  if (!Number.isFinite(dq) || dq < 0 || dq > 1) {
    errors.push(`${name}: data_quality 超出 [0,1]: ${data.data_quality}`);
  }
}

function checkRiskRanges(name, data) {
  const payload = data.payload || {};
  const total = Number(payload.total_score);
  if (!Number.isFinite(total) || total < 0 || total > 100) {
    errors.push(`${name}: total_score 超出 [0,100]: ${payload.total_score}`);
  }
  for (const dim of payload.dimensions || []) {
    const score = Number(dim.score);
    if (!Number.isFinite(score) || score < 0 || score > 100) {
      errors.push(`${name}: dimension ${dim.key} score 超出 [0,100]: ${dim.score}`);
    }
    for (const ind of dim.indicators || []) {
      if (ind.risk_score != null) {
        const rs = Number(ind.risk_score);
        if (!Number.isFinite(rs) || rs < 0 || rs > 100) {
          errors.push(`${name}: indicator ${ind.key} risk_score 超出 [0,100]: ${ind.risk_score}`);
        }
      }
    }
  }
  if (payload.confidence != null) {
    const c = Number(payload.confidence);
    if (!Number.isFinite(c) || c < 0 || c > 1) errors.push(`${name}: confidence 超出 [0,1]`);
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
  for (const [id, n] of ids) if (n > 1) errors.push(`news.json: 重复新闻 id ${id}（${n} 次）`);
  for (const [sig, n] of sigs) if (n > 1) errors.push(`news.json: 重复新闻 (title+source+published_at)（${n} 次）`);
}

function checkHistory() {
  for (const series of ["risk", "market"]) {
    for (const slice of ["30d", "90d", "daily"]) {
      const rel = `history/${series}/${slice}.json`;
      const rows = loadJson(rel);
      if (!rows) {
        warnings.push(`${rel} 缺失`);
        continue;
      }
      filesChecked += 1;
      if (!Array.isArray(rows)) {
        errors.push(`${rel}: 顶层应为数组`);
        continue;
      }
      for (const row of rows) {
        if (!row || typeof row !== "object") {
          errors.push(`${rel}: 行非对象`);
          continue;
        }
        if (!DATE_RE.test(String(row.date || ""))) errors.push(`${rel}: 行 date 非法: ${row.date}`);
        if (row.total_score != null) {
          const s = Number(row.total_score);
          if (!Number.isFinite(s) || s < 0 || s > 100) errors.push(`${rel}: total_score 超出 [0,100]`);
        }
      }
    }
  }
}

checkLatest();
checkNewsDuplicates();
checkHistory();

console.log(`[validate-json] 检查 ${filesChecked} 个文件，ERROR ${errors.length} 个，WARNING ${warnings.length} 个`);
for (const e of errors) console.log(`  [ERROR] ${e}`);
for (const w of warnings) console.log(`  [WARN ] ${w}`);

if (errors.length > 0) {
  console.log("[validate-json] 结果：未通过");
  process.exit(1);
}
console.log("[validate-json] 结果：通过");
process.exit(0);
