#!/usr/bin/env bash
# Generate (or verify) the frontend contract layer from the pydantic models.
#
#   scripts/gen_contracts.sh           # regenerate src/schemas/generated/
#   scripts/gen_contracts.sh --check   # exit 1 if the checked-in output is stale
#
# Interpreter resolution mirrors scripts/validate_data.sh: prefer the project venv, fall back
# to system python3. Unlike validate_data.sh there is no Node fallback — the models are the
# source of truth, so "pydantic is unavailable" means the contract cannot be verified at all,
# and passing silently would defeat the purpose of the check.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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
  echo "[gen_contracts] error: Python 3 not found (need .venv/bin/python or system python3)" >&2
  exit 1
fi

if ! "$PY" -c "import pydantic, yaml" >/dev/null 2>&1; then
  echo "[gen_contracts] error: pydantic and PyYAML are required. Try: pip install -e '.[dev]'" >&2
  exit 1
fi

exec "$PY" scripts/gen_ts_contracts.py "$@"
