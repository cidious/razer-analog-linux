#!/usr/bin/env bash
# Run razer-analog-linux from the project .venv (safe under sudo).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/.venv/bin/razer-analog-linux"

if [[ ! -x "$BIN" ]]; then
  echo "Missing $BIN — create it with:" >&2
  echo "  cd \"$ROOT\" && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 1
fi

exec "$BIN" "$@"
