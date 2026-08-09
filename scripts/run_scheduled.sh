#!/usr/bin/env bash
# Local scheduled task runner (implementation of docs/operations/scheduled-task.md §3).
# Flow: git pull → pipeline run → full validation → meaningful-change check → commit + push.
#
# Usage: scripts/run_scheduled.sh [--full|--market-only|--macro-only|--news-only|--fact-layer]
# Defaults to --full. Provider failures still degrade; repository and validation failures are fatal.
# Stable exits: 10 = environment/validation capability; 20 = pull; 21 = pipeline; 22 = validation;
# 23 = stage/commit; 24 = push or remote verification; 2 = invalid arguments.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if (($# > 1)); then
  echo "[scheduled] error: expected at most one pipeline mode" >&2
  exit 2
fi
MODE="${1:---full}"
PYTHON_BIN="${SCHEDULED_PYTHON:-$ROOT/.venv/bin/python}"
VALIDATE_SCRIPT="${VALIDATE_DATA_SCRIPT:-$ROOT/scripts/validate_data.sh}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[scheduled] error: Python pipeline interpreter unavailable" >&2
  exit 10
fi
if [[ ! -x "$VALIDATE_SCRIPT" ]]; then
  echo "[scheduled] error: validation script unavailable" >&2
  exit 10
fi
if ! "$PYTHON_BIN" -c "import pydantic, yaml, pydantic_settings" >/dev/null 2>&1; then
  echo "[scheduled] error: full Python validation dependencies unavailable" >&2
  exit 10
fi

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) start, mode $MODE"

# 0) Environment preparation (pull latest, including AI briefings and other collaborators' commits)
if ! git pull --rebase origin dev; then
  echo "[scheduled] error: git pull --rebase failed; collection did not start" >&2
  exit 20
fi

# 1) Run pipeline (a provider failure does not abort, see Architecture §8)
if ! "$PYTHON_BIN" -m pipeline.run "$MODE"; then
  echo "[scheduled] error: pipeline run failed, see artifacts/logs/run-report-*.json" >&2
  exit 21
fi

# 2) Data validation (T05 gate; no commit on ERROR)
if "$VALIDATE_SCRIPT" --scheduled; then
  :
else
  VALIDATION_STATUS=$?
  if ((VALIDATION_STATUS == 10)); then
    echo "[scheduled] error: validation capability unavailable, not committing" >&2
    exit 10
  fi
  echo "[scheduled] error: data validation failed, not committing" >&2
  exit 22
fi

# 3) Meaningful-change check + commit (avoid pointless Actions triggers, Architecture §8.14)
if git diff --quiet public/ config/; then
  echo "[scheduled] no meaningful changes, skipping commit"
  exit 0
fi

if ! git add public/ config/; then
  echo "[scheduled] error: failed to stage generated data" >&2
  exit 23
fi
if ! git commit -m "data: scheduled update $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null; then
  echo "[scheduled] error: commit failed; nothing was pushed" >&2
  exit 23
fi

if ! COMMIT_SHA="$(git rev-parse HEAD)" || [[ -z "$COMMIT_SHA" ]] || ! git show --quiet "$COMMIT_SHA"; then
  echo "[scheduled] error: committed data could not be verified locally" >&2
  exit 23
fi

if ! git push origin dev; then
  echo "[scheduled] error: push failed; local verified commit $COMMIT_SHA remains for retry" >&2
  exit 24
fi

if ! REMOTE_SHA="$(git ls-remote origin refs/heads/dev | awk '{print $1}')" || [[ "$REMOTE_SHA" != "$COMMIT_SHA" ]]; then
  echo "[scheduled] error: remote verification failed; local verified commit $COMMIT_SHA remains for retry" >&2
  exit 24
fi

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) done, published commit $COMMIT_SHA"
