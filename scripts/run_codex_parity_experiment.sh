#!/usr/bin/env bash
# Read-only Stage 1 Codex parity check. It never runs the data pipeline or contacts a remote.
# Reports are written to a temporary directory outside the repository.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${CODEX_PARITY_OUT_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/mrd-codex-parity.XXXXXX")}"
SCHEDULE="${CODEX_PARITY_SCHEDULE:-04:30 Europe/Dublin (WorkBuddy overnight news control)}"
mkdir -p "$OUT_DIR"
cd "$ROOT"

# Keep the comparison task explicitly credential-free even when the parent shell has a .env-backed session.
unset DATA_FRED_API_KEY DATA_COINGECKO_API_KEY DATA_FMP_API_KEY

before_status="$(git status --porcelain=v1 --untracked-files=all)"
before_diff="$(git diff --no-ext-diff --quiet; printf '%s' "$?")"
head="$(git rev-parse HEAD)"
branch="$(git branch --show-current)"
remote_ref="$(git show-ref --verify --hash refs/remotes/origin/dev 2>/dev/null || true)"
remote_url="$(git remote get-url origin 2>/dev/null || true)"

export MRD_PARITY_ROOT="$ROOT"
export MRD_PARITY_OUT_DIR="$OUT_DIR"
export MRD_PARITY_SCHEDULE="$SCHEDULE"
export MRD_PARITY_HEAD="$head"
export MRD_PARITY_BRANCH="$branch"
export MRD_PARITY_REMOTE_REF="$remote_ref"
export MRD_PARITY_REMOTE_URL="$remote_url"
export MRD_PARITY_BEFORE_STATUS="$before_status"
export MRD_PARITY_BEFORE_DIFF="$before_diff"

node <<'NODE'
const { execFileSync } = require("node:child_process");
const { mkdirSync, writeFileSync } = require("node:fs");
const { join } = require("node:path");

const root = process.env.MRD_PARITY_ROOT;
const outDir = process.env.MRD_PARITY_OUT_DIR;
mkdirSync(outDir, { recursive: true });
const runs = [];

for (let index = 1; index <= 3; index += 1) {
  const runId = `codex-stage1-${index}`;
  const started = new Date();
  let exitCode = 0;
  let output = "";
  try {
    output = execFileSync("node", ["scripts/validate-json.mjs"], {
      cwd: root,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      env: { PATH: process.env.PATH, NODE_ENV: "test" },
    });
  } catch (error) {
    exitCode = typeof error.status === "number" ? error.status : 1;
    output = `${error.stdout ?? ""}${error.stderr ?? ""}`;
  }
  const finished = new Date();
  let status = "";
  let diffState = "0";
  try {
    status = execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], { cwd: root, encoding: "utf8" }).trimEnd();
    execFileSync("git", ["diff", "--no-ext-diff", "--quiet"], { cwd: root, encoding: "utf8" });
  } catch (error) {
    if (error.status === 1) diffState = "1";
    if (error.status !== 0 && error.status !== 1) exitCode = exitCode || 1;
  }
  runs.push({
    run_id: runId,
    scheduled_at: process.env.MRD_PARITY_SCHEDULE,
    started_at: started.toISOString(),
    finished_at: finished.toISOString(),
    duration_seconds: (finished.getTime() - started.getTime()) / 1000,
    schedule_jitter_seconds: null,
    exit_code: exitCode,
    attempts: 1,
    approvals: "not applicable (read-only)",
    pause_resume: "not exercised",
    output: output.trim(),
    git: {
      head: process.env.MRD_PARITY_HEAD,
      branch: process.env.MRD_PARITY_BRANCH,
      status_unchanged: status === process.env.MRD_PARITY_BEFORE_STATUS,
      diff_unchanged: diffState === process.env.MRD_PARITY_BEFORE_DIFF,
      remote_ref: process.env.MRD_PARITY_REMOTE_REF,
      remote_url: process.env.MRD_PARITY_REMOTE_URL,
    },
    unknowns: [
      "Codex scheduler timezone resolution and jitter were not exercised by this manual Stage 1 run.",
      "Codex retry/replay, pause/resume, log export, and PR side effects remain unknown.",
    ],
  });
}

const report = {
  schema_version: "1.0.0",
  experiment: "market-risk-dashboard-codex-stage1",
  mode: "read-only",
  control: {
    platform: "WorkBuddy",
    schedule: process.env.MRD_PARITY_SCHEDULE,
    snapshot: process.env.MRD_PARITY_HEAD,
    validation_command: "node scripts/validate-json.mjs",
    output_schema: "codex-stage1-parity-report@1.0.0",
  },
  side_effect_policy: {
    network: false,
    secrets: false,
    repository_writes: false,
    pipeline_execution: false,
    git_mutation: false,
    remote_mutation: false,
  },
  runs,
  comparable: runs.length === 3 && runs.every((run) => run.exit_code === 0 && run.git.status_unchanged && run.git.diff_unchanged),
};

const reportPath = join(outDir, "codex-stage1-parity-report.json");
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
console.log(JSON.stringify({ report: reportPath, comparable: report.comparable, runs: runs.map(({ run_id, exit_code }) => ({ run_id, exit_code })) }));
process.exitCode = report.comparable ? 0 : 1;
NODE
