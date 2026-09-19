#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python 3.11 is required. Set PYTHON_BIN to a Python 3.11 interpreter." >&2
  exit 2
fi

if [[ "$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" != "3.11" ]]; then
  echo "ERROR: $PYTHON_BIN is not Python 3.11." >&2
  exit 2
fi

VALIDATION_TMP_BASE="${ADVANCED_VALIDATION_TMPDIR:-${TMPDIR:-}}"
if [[ -n "$VALIDATION_TMP_BASE" ]]; then
  mkdir -p "$VALIDATION_TMP_BASE"
  TMP_ROOT="$(mktemp -d "$VALIDATION_TMP_BASE/cti-rag-deps-XXXXXX")"
else
  TMP_ROOT="$(mktemp -d -t cti-rag-deps-XXXXXX)"
fi
trap 'rm -rf "$TMP_ROOT"' EXIT

if [[ -n "${ADVANCED_VALIDATION_PIP_CACHE_DIR:-}" ]]; then
  mkdir -p "$ADVANCED_VALIDATION_PIP_CACHE_DIR"
  export PIP_CACHE_DIR="$ADVANCED_VALIDATION_PIP_CACHE_DIR"
fi

section() {
  printf '\n================================================================\n%s\n================================================================\n' "$1"
}

create_env() {
  local name="$1"
  local requirements="$2"
  local env_dir="$TMP_ROOT/$name"

  section "Create $name dependency environment"
  "$PYTHON_BIN" -m venv "$env_dir"
  "$env_dir/bin/python" -m pip install --upgrade pip setuptools wheel
  "$env_dir/bin/python" -m pip install -r "$requirements"
  "$env_dir/bin/python" -m pip check
}

create_env offline requirements-advanced-validation.txt

section "Verify offline application dependency boundary"
"$TMP_ROOT/offline/bin/python" - <<'PY'
from importlib import metadata, util

fastapi = metadata.version("fastapi")
if fastapi != "0.115.14":
    raise SystemExit(f"expected fastapi 0.115.14, observed {fastapi}")
if util.find_spec("pycti") is not None:
    raise SystemExit("pycti must not be installed in the offline Prompt 04-22 environment")
print(f"offline FastAPI: {fastapi}")
print("offline pycti: absent (expected)")
PY

PYTHONPATH="$ROOT" "$TMP_ROOT/offline/bin/python" -m pytest   tests/unit/opencti/test_dependency_boundary.py -q

create_env opencti-live requirements-advanced-opencti.txt

section "Verify live OpenCTI dependency boundary"
"$TMP_ROOT/opencti-live/bin/python" - <<'PY'
from importlib import metadata

def version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    return tuple(int(part) for part in parts[:3])

pycti = metadata.version("pycti")
fastapi = metadata.version("fastapi")
if pycti != "7.260914.0":
    raise SystemExit(f"expected pycti 7.260914.0, observed {pycti}")
if version_tuple(fastapi) < (0, 129, 2):
    raise SystemExit(f"pycti live environment resolved incompatible fastapi {fastapi}")
print(f"live pycti: {pycti}")
print(f"live FastAPI: {fastapi}")
PY

if [[ "${OPENCTI_TEST_LIVE:-0}" == "1" ]]; then
  : "${OPENCTI_API_URL:?OPENCTI_TEST_LIVE=1 requires OPENCTI_API_URL}"
  : "${OPENCTI_API_TOKEN:?OPENCTI_TEST_LIVE=1 requires OPENCTI_API_TOKEN}"
  section "Run live read-only OpenCTI integration"
  PYTHONPATH="$ROOT" "$TMP_ROOT/opencti-live/bin/python" -m pytest     tests/integration/test_opencti_read.py -m opencti -q
else
  section "Live OpenCTI integration"
  echo "NOT_RUN: set OPENCTI_TEST_LIVE=1 plus OPENCTI_API_URL and OPENCTI_API_TOKEN to run it"
fi

section "Dependency profile validation passed"
echo "VALIDATION_ADVANCED_DEPENDENCY_PROFILES_PASSED"
