#!/usr/bin/env node
/**
 * Build-time precompression (Architecture §5#3 / PRD §23: JSON files support gzip or Brotli).
 *
 * GitHub Pages' automatic compression of .json is unreliable; this script pre-generates
 * .gz (gzip) and .br (brotli) variants for static assets above the size threshold at the dist stage.
 * On servers that support precompressed variants (nginx gzip_static / CDN), browsers can
 * hit the compressed files directly; if Pages ignores the variants, only a few extra files
 * exist, with no side effects.
 *
 * Usage:
 *   node scripts/precompress.mjs [--dist dist] [--min-size 1024]
 * Toggle: set the environment variable NO_PRECOMPRESS=1 to skip (enabled by default).
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
  console.log("[precompress] NO_PRECOMPRESS=1, skipping");
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
  console.log(`[precompress] dist directory does not exist: ${DIST} (skipping)`);
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
  `[precompress] dist precompression complete: gzip ${gzCount}, brotli ${brCount}, skipped ${skipped} file(s) < ${MIN_SIZE}B`,
);
