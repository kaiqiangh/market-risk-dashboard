#!/usr/bin/env bash
# Local one-click data validation (Architecture §5#1 / PRD §20.2).
# Equivalent to the checks in .github/workflows/validate-data.yml, for local Scheduled Tasks / dev machines:
#   Schema validation / required fields / timestamps / data quality / risk score ranges / NaN·Infinity /
#   duplicate news / stale data / unknown language key / missing zh-CN/en files / AI bilingual conclusion mismatch.
#
# Usage:
#   scripts/validate_data.sh [--data-dir <public/data>]
#
# Exit code: 0 = pass (may include WARNING); 1 = has ERROR.
# Prefer .venv/bin/python (full Pydantic validation); fall back to Node structural validation when pydantic is unavailable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Locate the Python interpreter
PY=""
for candidate in ".venv/bin/python" ".venv/Scripts/python.exe"; do
  if [[ -x "$candidate" ]]; then
    PY="$candidate"
    break
  fi
done
if [[ -z "$PY" ]]; then
  PY="$(command -v python3 || true)"
fi
if [[ -z "$PY" ]]; then
  echo "[validate_data] error: Python 3 not found (need .venv/bin/python or system python3)" >&2
  exit 1
fi

# Full validation (Pydantic available)
if "$PY" -c "import pydantic, yaml, pydantic_settings" >/dev/null 2>&1; then
  exec "$PY" -m pipeline.validation.ci_checks "$@"
fi

# Fallback: Node structural validation (no Python dependencies)
if command -v node >/dev/null 2>&1 && [[ -f scripts/validate-json.mjs ]]; then
  echo "[validate_data] warning: pydantic not installed, falling back to Node structural validation (covers Schema/required/range/NaN/duplicates, not bilingual consistency)" >&2
  exec node scripts/validate-json.mjs "$@"
fi

echo "[validate_data] error: neither pydantic nor node available, cannot validate" >&2
exit 1
