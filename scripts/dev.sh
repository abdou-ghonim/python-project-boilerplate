#!/usr/bin/env bash
# Run the API and the Vite dev server together, and stop both on Ctrl-C.
#
#   scripts/dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."

[[ -f .env ]] || { echo "No .env — copy .env.example and set SECRET_KEY."; exit 1; }
[[ -d .venv ]] || { echo "No .venv — run scripts/setup.sh first."; exit 1; }

# shellcheck disable=SC1091
source .venv/bin/activate
export FLASK_APP=run.py

cleanup() { kill 0; }
trap cleanup EXIT INT TERM

flask run --port "${API_PORT:-5000}" --reload &
(cd frontend && npm run dev) &

echo "API      http://localhost:${API_PORT:-5000}"
echo "Frontend http://localhost:5173"
wait
