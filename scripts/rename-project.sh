#!/usr/bin/env bash
# Rebrand a copy of this boilerplate.
#
#   scripts/rename-project.sh "Licence Portal" licence-portal
#
# Rewrites the display name and the slug across config, package.json, compose
# and the README. Run it once, immediately after copying the tree — it is a
# search-and-replace, not a migration.
set -euo pipefail
cd "$(dirname "$0")/.."

[[ $# -eq 2 ]] || { echo 'Usage: scripts/rename-project.sh "<Display Name>" <slug>' >&2; exit 1; }
name="$1"
slug="$2"

[[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
    echo "Error: the slug must be lowercase letters, digits and hyphens." >&2; exit 1; }

if [[ -d .git ]] && ! git diff --quiet 2>/dev/null; then
    echo "Warning: you have uncommitted changes; this rewrites files in place."
    read -rp "Continue? [y/N] " reply
    [[ "$reply" == [yY] ]] || exit 1
fi

replace() {   # file old new
    [[ -f "$1" ]] && sed -i "s|$2|$3|g" "$1"
}

replace .env.example "Python Project Boilerplate" "$name"
replace .env.example "APP_SLUG=boilerplate" "APP_SLUG=${slug}"
replace config.py '"Python Project Boilerplate"' "\"${name}\""
replace config.py '"boilerplate")' "\"${slug}\")"
replace frontend/package.json '"boilerplate-frontend"' "\"${slug}-frontend\""
replace frontend/index.html "Python Project Boilerplate" "$name"
replace scripts/docker-deploy.sh "boilerplate-app" "${slug}-app"
replace README.md "Python Project Boilerplate" "$name"

[[ -f .env ]] && {
    replace .env "APP_NAME=.*" "APP_NAME=\"${name}\""
    replace .env "APP_SLUG=.*" "APP_SLUG=${slug}"
}

echo "Renamed to '${name}' (${slug})."
echo "Check: grep -ri boilerplate --exclude-dir={.git,node_modules,.venv} ."
