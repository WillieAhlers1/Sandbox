#!/usr/bin/env bash
# docker_build_base.sh — Build and push the base-python foundation image.
#
# This image is tagged as :latest only. It changes infrequently (Python version
# upgrades, system package changes) and is shared across all projects/branches.
# Run this separately from docker_build.sh — typically once when setting up a
# new project or when the base Dockerfile changes.
#
# Usage:
#   ./scripts/docker_build_base.sh [--push]
#
# Environment variables:
#   GCP_AR_HOST     — Artifact Registry host (e.g. us-east4-docker.pkg.dev)
#   GCP_PROJECT_ID  — GCP project ID
#   GCP_AR_REPO     — AR repository name (e.g. mlplatform-second-run)

set -euo pipefail

PUSH=false
[[ "${1:-}" == "--push" ]] && PUSH=true

DOCKERFILE="docker/base/base-python/Dockerfile"
if [ ! -f "$DOCKERFILE" ]; then
    echo "[base-python] Dockerfile not found at ${DOCKERFILE}" >&2
    exit 1
fi

# AR prefix (empty = local-only build)
_ar_prefix() {
    local host="${GCP_AR_HOST:-${AR_HOST:-}}"
    local project="${GCP_PROJECT_ID:-${GCP_PROJECT:-}}"
    local repo="${GCP_AR_REPO:-${AR_REPO:-}}"
    if [ -n "$host" ] && [ -n "$project" ] && [ -n "$repo" ]; then
        echo "${host}/${project}/${repo}"
    fi
}

PREFIX=$(_ar_prefix)
if [ -n "$PREFIX" ]; then
    IMAGE="${PREFIX}/base-python:latest"
else
    IMAGE="base-python:latest"
fi

echo "[base-python] Building ${IMAGE}"
docker buildx build --platform linux/amd64 --load \
    -t "${IMAGE}" -f "${DOCKERFILE}" "docker/base/base-python"

if [ "$PUSH" = true ] && [ -n "$PREFIX" ]; then
    echo "[base-python] Pushing ${IMAGE}"
    docker push "${IMAGE}"
fi

echo "[base-python] Done: ${IMAGE}"
