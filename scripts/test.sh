#!/usr/bin/env bash
# Run the Python test suite and the frontend type-check.
set -euo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
[[ -d .venv ]] && source .venv/bin/activate

echo "==> pytest"
pytest "$@"

if [[ -d frontend/node_modules ]]; then
    echo "==> tsc"
    (cd frontend && npx tsc -b --noEmit)
else
    echo "==> skipping tsc (frontend/node_modules not installed)"
fi
