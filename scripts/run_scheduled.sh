#!/usr/bin/env bash
# Local scheduled task runner (implementation of docs/operations/scheduled-task.md §3).
# Flow: git pull → pipeline run → data validation → meaningful-change check → commit + push.
#
# Usage: scripts/run_scheduled.sh [--full|--market-only|--macro-only|--news-only|--fact-layer]
# Defaults to --full. On network outage/failure, degrade per §4: no abort, no silent failure, keep logs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:---full}"

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) start, mode $MODE"

# 0) Environment preparation (pull latest, including AI briefings and other collaborators' commits)
if ! git pull --rebase origin dev 2>/dev/null; then
  echo "[scheduled] warning: git pull failed (possibly offline), continuing with local state" >&2
fi

# 1) Run pipeline (a provider failure does not abort, see Architecture §8)
if ! .venv/bin/python -m pipeline.run "$MODE"; then
  echo "[scheduled] error: pipeline run failed, see artifacts/logs/run-report-*.json" >&2
  exit 1
fi

# 2) Data validation (T05 gate; no commit on ERROR)
if ! scripts/validate_data.sh; then
  echo "[scheduled] error: data validation failed, not committing" >&2
  exit 1
fi

# 3) Meaningful-change check + commit (avoid pointless Actions triggers, Architecture §8.14)
if git diff --quiet public/ config/; then
  echo "[scheduled] no meaningful changes, skipping commit"
  exit 0
fi

git add public/ config/
git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null || true

if ! git push origin dev; then
  echo "[scheduled] error: push failed (network/conflict); committed locally, run git pull --rebase and retry push later" >&2
  exit 1
fi

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) done"
