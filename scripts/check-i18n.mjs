#!/usr/bin/env node
/**
 * i18n 翻译文件校验（deploy-pages.yml「校验翻译文件」步骤，零依赖）。
 * 检查：
 * 1. 命名空间文件齐全（zh-CN + en 各 9 个）。
 * 2. 未知语言目录（只允许 zh-CN / en）。
 * 3. 中文文件缺失 key（en 有而 zh 无）。
 * 4. 英文文件缺失 key（zh 有而 en 无）。
 *
 * 用法：node scripts/check-i18n.mjs
 * 退出码：0 = 通过；1 = 存在缺失。
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
    errors.push(`${lang}/${ns}.json: 无法解析 JSON: ${e.message}`);
    return null;
  }
}

// 1) 未知语言目录
const langs = readdirSync(LOCALES, { withFileTypes: true })
  .filter((e) => e.isDirectory())
  .map((e) => e.name);
for (const lang of langs) {
  if (lang !== "zh-CN" && lang !== "en") {
    errors.push(`未知语言目录: ${lang}（只允许 zh-CN / en）`);
  }
}

// 2) 命名空间齐全
for (const lang of ["zh-CN", "en"]) {
  for (const ns of NAMESPACES) {
    if (!existsSync(join(LOCALES, lang, `${ns}.json`))) {
      errors.push(`${lang}/${ns}.json 缺失`);
    }
  }
}

// 3/4) key 完整性（双向）
for (const ns of NAMESPACES) {
  const zh = loadNamespace("zh-CN", ns);
  const en = loadNamespace("en", ns);
  if (zh === null || en === null) continue;
  const zhKeys = new Set(flattenKeys(zh));
  const enKeys = new Set(flattenKeys(en));
  const missingInZh = [...enKeys].filter((k) => !zhKeys.has(k));
  const missingInEn = [...zhKeys].filter((k) => !enKeys.has(k));
  if (missingInZh.length > 0) errors.push(`${ns}: 中文缺失 key（en 有而 zh 无）: ${missingInZh.join(", ")}`);
  if (missingInEn.length > 0) errors.push(`${ns}: 英文缺失 key（zh 有而 en 无）: ${missingInEn.join(", ")}`);
}

if (errors.length > 0) {
  console.log("[check-i18n] 未通过：");
  for (const e of errors) console.log(`  - ${e}`);
  process.exit(1);
}
console.log(`[check-i18n] 通过：zh-CN/en 各 ${NAMESPACES.length} 个命名空间 key 完整`);
process.exit(0);
