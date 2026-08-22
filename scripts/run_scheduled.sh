#!/usr/bin/env bash
# Local scheduled task runner (implementation of docs/operations/scheduled-task.md §3).
# Flow: lock → git pull → pipeline run → full validation → meaningful-change check → commit + push.
#
# Usage: scripts/run_scheduled.sh [--full|--market-only|--macro-only|--news-only|--fact-layer]
# Defaults to --full. Provider failures still degrade; repository and validation failures are fatal.
# Stable exits: 10 = environment/validation capability; 20 = pull; 21 = pipeline; 22 = validation;
# 23 = stage/commit; 24 = push or remote verification; 25 = another instance already running;
# 2 = invalid arguments.
#
# Environment knobs (#190): SCHEDULED_BRANCH (default dev), SCHEDULED_TIMEOUT_PIPELINE (default
# 3600s), SCHEDULED_TIMEOUT_VALIDATE (default 1800s), SCHEDULED_LOCK_STALE (default 7200s),
# SCHEDULED_LOCK_DIR (test override), SCHEDULED_LOCK_MODE (auto|flock|mkdir).
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
BRANCH="${SCHEDULED_BRANCH:-dev}"

#: Timeouts (#190): every network/bulk step gets a ceiling so a hung remote cannot wedge
#: the cron slot forever - collection AND validation alike (a hung validator would hold
#: the lock past its stale window and invite a concurrent fire). macOS lacks coreutils
#: timeout; gtimeout (coreutils) is accepted; with neither, steps run bare WITH a visible
#: warning - a missing optional binary must not stop data collection (#190 review).
#: Resolved with explicit probes rather than fallback chains (#190 pin): an optional
#: convenience binary is a documented absence, not a swallowed failure.
TIMEOUT_BIN=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN="$(command -v timeout)"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN="$(command -v gtimeout)"
fi

run_with_timeout() {
  local secs="$1"
  shift
  if [[ -n "$TIMEOUT_BIN" ]]; then
    "$TIMEOUT_BIN" "$secs" "$@"
  else
    echo "[scheduled] warn: no timeout/gtimeout on PATH; unbounded: $*" >&2
    "$@"
  fi
}

#: Single-instance guard (#190): overlapping cron fires would interleave git state.
#: flock where available; otherwise a portable mkdir lock (atomic) with stale-entry
#: recovery so a crashed run cannot wedge the scheduler forever. The lock lives under
#: .git/ by default: never committed, never pushed. SCHEDULED_LOCK_MODE forces a
#: mechanism ("flock"|"mkdir") - tests need determinism on hosts that have one but not
#: the other.
LOCK_DIR="${SCHEDULED_LOCK_DIR:-$ROOT/.git/scheduled.lock}"
LOCK_STALE_SECS="${SCHEDULED_LOCK_STALE:-7200}"
FLOCK_BIN=""
if command -v flock >/dev/null 2>&1; then
  FLOCK_BIN="$(command -v flock)"
fi
case "${SCHEDULED_LOCK_MODE:-auto}" in
  auto)   : ;;
  flock)  FLOCK_BIN="${FLOCK_BIN:-flock}" ;;
  mkdir)  FLOCK_BIN="" ;;
  *) echo "[scheduled] error: SCHEDULED_LOCK_MODE must be auto|flock|mkdir" >&2; exit 10 ;;
esac

acquire_lock() {
  if [[ -n "$FLOCK_BIN" ]]; then
    exec 9>"$LOCK_DIR.lockfile"
    if ! flock -n 9; then
      echo "[scheduled] error: another instance holds the flock lock" >&2
      exit 25
    fi
    return
  fi
  # The mkdir fallback registers EXIT cleanup ONLY in its own winner branches: a loser
  # must never rmdir the winner's lock. Cleanup redirects stderr because noise from an
  # already-removed dir is expected there; it swallows no FAILURE (#190 review).
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT
    return
  fi
  local now mtime
  now="$(date +%s)"
  mtime="$(stat -f %m "$LOCK_DIR" 2>/dev/null || stat -c %Y "$LOCK_DIR" 2>/dev/null || echo "$now")"
  if ((now - mtime > LOCK_STALE_SECS)); then
    echo "[scheduled] warn: removing stale lock (age $((now - mtime))s > $LOCK_STALE_SECS)" >&2
    rm -rf "$LOCK_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
      trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT
      return
    fi
  fi
  echo "[scheduled] error: another instance appears to be running (lock $LOCK_DIR)" >&2
  exit 25
}

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

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) start, mode $MODE, branch $BRANCH"

acquire_lock

# 0) Environment preparation (pull latest, including AI briefings and other collaborators’ commits)
if ! run_with_timeout 120 git pull --rebase origin "$BRANCH"; then
  echo "[scheduled] error: git pull --rebase failed; collection did not start" >&2
  exit 20
fi

# 1) Run pipeline (a provider failure does not abort, see Architecture §8)
if ! run_with_timeout "${SCHEDULED_TIMEOUT_PIPELINE:-3600}" "$PYTHON_BIN" -m pipeline.run "$MODE"; then
  echo "[scheduled] error: pipeline run failed, see artifacts/logs/run-report-*.json" >&2
  exit 21
fi

# 2) Data validation (T05 gate; no commit on ERROR). Bulk step => also time-bounded
#    (#190 review): a hung validator would otherwise hold the lock past its stale window.
#    Explicit $? capture makes the sequencing undeniable under set -e.
set +e
run_with_timeout "${SCHEDULED_TIMEOUT_VALIDATE:-1800}" "$VALIDATE_SCRIPT" --scheduled
VALIDATION_STATUS=$?
set -e
if ((VALIDATION_STATUS == 0)); then
  :
elif ((VALIDATION_STATUS == 10)); then
  echo "[scheduled] error: validation capability unavailable, not committing" >&2
  exit 10
else
  echo "[scheduled] error: data validation failed (exit $VALIDATION_STATUS), not committing" >&2
  exit 22
fi

# 3) Meaningful-change check + commit (#190): porcelain also sees NEW UNTRACKED files,
#    which `git diff --quiet` silently ignored - a brand-new dataset would never have
#    been published by the scheduled run.
if [[ -z "$(git status --porcelain -- public/ config/)" ]]; then
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

if ! run_with_timeout 300 git push origin "$BRANCH"; then
  echo "[scheduled] error: push failed; local verified commit $COMMIT_SHA remains for retry" >&2
  exit 24
fi

if ! REMOTE_SHA="$(run_with_timeout 30 git ls-remote origin "refs/heads/$BRANCH" | awk '{print $1}')" \
   || [[ "$REMOTE_SHA" != "$COMMIT_SHA" ]]; then
  echo "[scheduled] error: remote verification failed; local verified commit $COMMIT_SHA remains for retry" >&2
  exit 24
fi

echo "[scheduled] $(date -u +%Y-%m-%dT%H:%M:%SZ) done, published commit $COMMIT_SHA"

