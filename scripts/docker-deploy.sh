#!/usr/bin/env bash
# Build and push the application image, tagged with a release version.
#
#   scripts/docker-deploy.sh 1.0.0                      build + push
#   scripts/docker-deploy.sh 1.0.0 --no-push            build only
#
# The database driver is baked in at build time, so the image is built for the
# provider it will run against:
#   DB_PROVIDER=postgresql scripts/docker-deploy.sh 1.0.0
set -euo pipefail
cd "$(dirname "$0")/.."

usage() { echo "Usage: $0 <version> [--no-push]" >&2; exit 1; }

[[ $# -ge 1 ]] || usage
version="$1"
push=1
[[ "${2:-}" == "--no-push" ]] && push=0
[[ $# -le 2 ]] || usage

if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]; then
    echo "Error: '$version' is not a version like 1.0.0" >&2
    exit 1
fi

REGISTRY="${REGISTRY:-your-registry}"
IMAGE="${IMAGE_NAME:-boilerplate-app}"
PROVIDER="${DB_PROVIDER:-sqlite}"
WITH_OIDC="${WITH_OIDC:-false}"
tag="${REGISTRY}/${IMAGE}:${version}"

echo "==> Building $tag (DB_PROVIDER=$PROVIDER, WITH_OIDC=$WITH_OIDC)"
docker build \
    --build-arg "DB_PROVIDER=${PROVIDER}" \
    --build-arg "WITH_OIDC=${WITH_OIDC}" \
    -t "$tag" .

if (( push )); then
    echo "==> Pushing $tag"
    docker push "$tag"
fi

echo "Done: $tag"
