#!/usr/bin/env node
/**
 * 构建期预压缩（架构 §5#3 / PRD §23：JSON 文件支持 gzip 或 Brotli）。
 *
 * GitHub Pages 对 .json 的自动压缩行为不可靠；本脚本在 dist 阶段为
 * 超过阈值的静态资源预生成 .gz（gzip）与 .br（brotli）变体。
 * 若部署到支持 precompressed 变体的服务器（nginx gzip_static / CDN），
 * 浏览器可直接命中压缩文件；若 Pages 忽略变体则仅多出若干文件，无副作用。
 *
 * 用法：
 *   node scripts/precompress.mjs [--dist dist] [--min-size 1024]
 * 开关：设置环境变量 NO_PRECOMPRESS=1 可跳过（默认开启）。
 */
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync, brotliCompressSync } from "node:zlib";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const DIST = process.argv.includes("--dist")
  ? resolve(process.argv[process.argv.indexOf("--dist") + 1])
  : join(ROOT, "dist");
const MIN_SIZE = process.argv.includes("--min-size")
  ? Number(process.argv[process.argv.indexOf("--min-size") + 1])
  : 1024;

if (process.env.NO_PRECOMPRESS === "1") {
  console.log("[precompress] NO_PRECOMPRESS=1，跳过");
  process.exit(0);
}

const EXTENSIONS = new Set([".json", ".js", ".css", ".html", ".svg", ".txt", ".xml"]);

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

if (!existsSync(DIST)) {
  console.log(`[precompress] dist 目录不存在: ${DIST}（跳过）`);
  process.exit(0);
}

let gzCount = 0;
let brCount = 0;
let skipped = 0;

for (const file of walk(DIST)) {
  const ext = file.slice(file.lastIndexOf(".")).toLowerCase();
  if (!EXTENSIONS.has(ext)) continue;
  const size = statSync(file).size;
  if (size < MIN_SIZE) {
    skipped += 1;
    continue;
  }
  const content = readFileSync(file);
  const gz = gzipSync(content, { level: 9 });
  const br = brotliCompressSync(content);
  writeFileSync(`${file}.gz`, gz);
  writeFileSync(`${file}.br`, br);
  gzCount += 1;
  brCount += 1;
}

console.log(
  `[precompress] dist 预压缩完成：gzip ${gzCount} 个，brotli ${brCount} 个，跳过 <${MIN_SIZE}B 的 ${skipped} 个`,
);
