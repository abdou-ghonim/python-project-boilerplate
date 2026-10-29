#!/usr/bin/env bash
# First-run setup: virtualenv, dependencies, .env, database, admin, demo data.
#
#   scripts/setup.sh                 sqlite + local auth
#   DB_PROVIDER=postgresql scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PROVIDER="${DB_PROVIDER:-sqlite}"

if [[ ! -d .venv ]]; then
    echo "==> Creating .venv"
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing Python dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
[[ -f "requirements/${PROVIDER}.txt" ]] && pip install --quiet -r "requirements/${PROVIDER}.txt"
pip install --quiet -r requirements/dev.txt

if [[ ! -f .env ]]; then
    echo "==> Creating .env with a generated SECRET_KEY"
    cp .env.example .env
    key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    # The placeholder key is refused at startup, so replace it before first run.
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${key}|" .env
    sed -i "s|^DB_PROVIDER=.*|DB_PROVIDER=${PROVIDER}|" .env
fi

echo "==> Installing frontend dependencies"
(cd frontend && npm install --silent)

export FLASK_APP=run.py
echo "==> Applying sql/${PROVIDER}/*.sql and creating the default admin"
flask db-apply
flask seed-demo --count 25

echo
echo "Done. Start everything with: scripts/dev.sh"
