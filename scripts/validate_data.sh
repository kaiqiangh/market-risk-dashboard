#!/usr/bin/env bash
# Local one-click data validation (Architecture §5#1 / PRD §20.2).
# Equivalent to the checks in .github/workflows/validate-data.yml, for local Scheduled Tasks / dev machines:
#   Schema validation / required fields / timestamps / data quality / risk score ranges / NaN·Infinity /
#   duplicate news / stale data / unknown language key / missing zh-CN/en files / AI bilingual conclusion mismatch.
#
# Usage:
#   scripts/validate_data.sh [--data-dir <public/data>]
#   scripts/validate_data.sh --diagnostic-reduced [--data-dir <public/data>]
#
# Exit codes: 0 = pass; 10 = validation capability unavailable; 11 = validation failed;
# 2 = invalid arguments. Full Pydantic validation is mandatory by default. The reduced
# mode is an explicit developer diagnostic and is rejected by scheduled/production callers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DATA_ARGS=()
REDUCED_DIAGNOSTIC=0
SCHEDULED_PATH=0
while (($# > 0)); do
  case "$1" in
    --data-dir)
      if (($# < 2)); then
        echo "[validate_data] error: --data-dir requires a path" >&2
        exit 2
      fi
      DATA_ARGS+=("--data-dir" "$2")
      shift 2
      ;;
    --diagnostic-reduced)
      REDUCED_DIAGNOSTIC=1
      shift
      ;;
    --scheduled|--production)
      SCHEDULED_PATH=1
      shift
      ;;
    *)
      echo "[validate_data] error: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "${VALIDATE_DATA_PRODUCTION:-0}" == "1" ]]; then
  SCHEDULED_PATH=1
fi
if ((REDUCED_DIAGNOSTIC && SCHEDULED_PATH)); then
  echo "[validate_data] error: reduced diagnostic mode is not allowed for scheduled/production validation" >&2
  exit 10
fi

# Secret gate (S-1/#92): no configured API key (pattern or literal) may reach the
# published tree or the run logs. Runs before the data checks so a leak fails loudly.
if ! command -v node >/dev/null 2>&1; then
  echo "[validate_data] error: Node runtime unavailable; mandatory secret scan cannot run" >&2
  exit 10
fi
if ! node scripts/scan-secrets.mjs --root "$ROOT"; then
  echo "[validate_data] error: mandatory secret scan failed" >&2
  exit 11
fi

# Explicit developer diagnostic mode: this is never a production-quality result.
if ((REDUCED_DIAGNOSTIC)); then
  echo "[validate_data] mode=reduced-diagnostic (Node structural checks only; not publishable)" >&2
  NODE_STATUS=0
  if ((${#DATA_ARGS[@]} > 0)); then
    node scripts/validate-json.mjs "${DATA_ARGS[@]}" || NODE_STATUS=$?
  else
    node scripts/validate-json.mjs || NODE_STATUS=$?
  fi
  if ((NODE_STATUS == 0)); then
    echo "[validate_data] result: passed in reduced-diagnostic mode" >&2
    exit 0
  fi
  echo "[validate_data] error: reduced structural validation failed" >&2
  exit 11
fi

# Locate the Python interpreter. VALIDATE_DATA_PYTHON is intentionally injectable for
# diagnostics/tests; production callers still use the project venv or system python3.
PY="${VALIDATE_DATA_PYTHON:-}"
if [[ -z "$PY" ]]; then
  for candidate in ".venv/bin/python" ".venv/Scripts/python.exe"; do
    if [[ -x "$candidate" ]]; then
      PY="$candidate"
      break
    fi
  done
fi
if [[ -z "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" || ! -x "$PY" ]]; then
  echo "[validate_data] error: Python validation interpreter unavailable" >&2
  exit 10
fi

# Full validation (Pydantic is mandatory in the default path).
if ! "$PY" -c "import pydantic, yaml, pydantic_settings" >/dev/null 2>&1; then
  echo "[validate_data] error: full Python validation dependencies unavailable (use --diagnostic-reduced only for local diagnostics)" >&2
  exit 10
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[validate_data] error: npm unavailable; contract drift gate cannot run" >&2
  exit 10
fi
if ! npm run check:contracts; then
  echo "[validate_data] error: generated frontend contracts are out of date" >&2
  exit 11
fi

VALIDATION_STATUS=0
if ((${#DATA_ARGS[@]} > 0)); then
  "$PY" -m pipeline.validation.ci_checks "${DATA_ARGS[@]}" || VALIDATION_STATUS=$?
else
  "$PY" -m pipeline.validation.ci_checks || VALIDATION_STATUS=$?
fi

# Theme symbol health gate (#175): a configured theme symbol missing/degraded in the
# latest run telemetry must fail validation — the chronic Degraded cascade (#171) began
# with two delisted theme symbols that no gate noticed for weeks.
if ((${#DATA_ARGS[@]} > 0)); then
  "$PY" -m pipeline.validation.symbol_health "${DATA_ARGS[@]}" || VALIDATION_STATUS=$?
else
  "$PY" -m pipeline.validation.symbol_health || VALIDATION_STATUS=$?
fi
if ((VALIDATION_STATUS == 0)); then
  exit 0
fi
echo "[validate_data] error: full Python validation failed" >&2
exit 11
