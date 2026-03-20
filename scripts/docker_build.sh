#!/usr/bin/env bash
# docker_build.sh — Build base image + one image per pipeline, optionally push.
#
# Usage:
#   ./scripts/docker_build.sh [--push] [pipelines_dir]
#
# Image hierarchy (build order):
#   base-python → {pipeline-name} (one per pipeline directory)
#
# Each pipeline image includes: framework code + pipeline code + all deps.
# Steps run directly inside the pipeline image via:
#   python -m pipelines.<name>.steps.<step_name>
#
# Environment variables:
#   AR_HOST     — Artifact Registry host (e.g. us-central1-docker.pkg.dev)
#   GCP_PROJECT — GCP project ID
#   AR_REPO     — AR repository name (e.g. dsci-gcpdemo)
#   IMAGE_TAG   — Tag for all built images (default: {branch}-{short_sha})

set -euo pipefail

PUSH=false
PIPELINES_DIR="pipelines"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --push) PUSH=true; shift ;;
        *)      PIPELINES_DIR="$1"; shift ;;
    esac
done

# Derive tag from git branch + short SHA (matching gcp_ml_framework/naming.py)
# Can be overridden via IMAGE_TAG env var.
if [ -z "${IMAGE_TAG:-}" ]; then
    _branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//')
    _sha=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    TAG="${_branch}-${_sha}"
else
    TAG="${IMAGE_TAG}"
fi
BUILT_IMAGES=()

_ar_prefix() {
    # Returns the AR URI prefix, or empty string for local-only builds.
    if [ -n "${AR_HOST:-}" ] && [ -n "${GCP_PROJECT:-}" ] && [ -n "${AR_REPO:-}" ]; then
        echo "${AR_HOST}/${GCP_PROJECT}/${AR_REPO}"
    fi
}

_full_tag() {
    # Returns the full image tag: AR prefix + name:tag, or just name:tag locally.
    local name="$1"
    local prefix
    prefix=$(_ar_prefix)
    if [ -n "$prefix" ]; then
        echo "${prefix}/${name}:${TAG}"
    else
        echo "${name}:${TAG}"
    fi
}

_slugify() {
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//'
}

_build() {
    # Build a Docker image. Args: image_tag dockerfile context [extra docker args...]
    local image_tag="$1"
    local dockerfile="$2"
    local context="$3"
    shift 3

    echo "[docker_build] Building ${image_tag}"
    if command -v docker &> /dev/null; then
        if [ "$PUSH" = true ] && [ -n "$(_ar_prefix)" ]; then
            # Build, load locally (for use as base in subsequent builds), then push
            docker buildx build --platform linux/amd64 --load \
                -t "${image_tag}" -f "${dockerfile}" "$@" "${context}"
            docker push "${image_tag}"
        else
            docker buildx build --platform linux/amd64 --load \
                -t "${image_tag}" -f "${dockerfile}" "$@" "${context}"
        fi
        BUILT_IMAGES+=("${image_tag}")
    else
        echo "[docker_build] Docker not available — skipping"
    fi
}

# ── Layer 0: base-python ─────────────────────────────────────────────────────

_build_base_python() {
    local dockerfile="docker/base/base-python/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo "[docker_build] base-python Dockerfile not found — skipping"
        return
    fi
    _build "$(_full_tag base-python)" "$dockerfile" "docker/base/base-python"
}

# ── Layer 1: per-pipeline images ─────────────────────────────────────────────

_build_pipeline() {
    # Build one image for a pipeline directory.
    # Uses the base-ml Dockerfile (full deps + source), named after the pipeline.
    local pipeline_dir="$1"
    local pipeline_name
    pipeline_name=$(basename "$pipeline_dir")

    # Skip directories without a pipeline.py
    if [ ! -f "${pipeline_dir}/pipeline.py" ]; then
        echo "[docker_build] ${pipeline_name}: no pipeline.py — skipping"
        return
    fi

    local dockerfile="docker/base/base-ml/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo "[docker_build] base-ml Dockerfile not found — skipping"
        return
    fi

    local image_name
    image_name=$(_slugify "$pipeline_name")

    _build "$(_full_tag "$image_name")" "$dockerfile" "." \
        --build-arg "BASE_IMAGE=$(_full_tag base-python)"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo "[docker_build] Tag: ${TAG}"
    echo "[docker_build] Push: ${PUSH}"
    echo ""

    # Layer 0: foundation
    _build_base_python

    # Layer 1: one image per pipeline
    for pipeline_dir in "${PIPELINES_DIR}"/*/; do
        _build_pipeline "$pipeline_dir"
    done

    echo ""
    echo "[docker_build] Done. Built ${#BUILT_IMAGES[@]} image(s)."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
