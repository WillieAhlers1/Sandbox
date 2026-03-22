#!/usr/bin/env bash
# docker_build.sh — Build pipeline Docker images (train, serve, pipeline-specific).
#
# Assumes base-python:latest already exists (built separately via docker_build_base.sh).
#
# Usage:
#   ./scripts/docker_build.sh [--push] [--pipeline <name>]
#
# Image hierarchy (build order):
#   1. docker/train.Dockerfile                   → train:{tag}            (default training)
#   2. docker/serve.Dockerfile                   → serve:{tag}            (default serving)
#   3. docker/pipelines/{name}/*.Dockerfile      → {name}--{stem}:{tag}  (per-pipeline)
#
# BASE_IMAGE resolution:
#   Data scientists write `ARG BASE_IMAGE=<stem>` in their Dockerfiles using
#   simple stem names (e.g., "base-python", "train", "house_price_train"). The
#   build script maintains a registry of stem → full tag and auto-resolves.
#
# Image name resolution is delegated to NamingConvention.docker_image_name()
# ensuring bash and Python use identical naming.
#
# Environment variables:
#   GCP_AR_HOST     — Artifact Registry host (e.g. us-east4-docker.pkg.dev)
#   GCP_PROJECT_ID  — GCP project ID
#   GCP_AR_REPO     — AR repository name (e.g. mlplatform-third-run)
#   IMAGE_TAG       — Tag override (default: {branch}-{short_sha})

set -euo pipefail

PUSH=false
PIPELINE_FILTER=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --push) PUSH=true; shift ;;
        --pipeline) PIPELINE_FILTER="$2"; shift 2 ;;
        *)
            echo "[docker_build] Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# Derive tag from git branch + short SHA (matching NamingConvention.image_tag)
if [ -z "${IMAGE_TAG:-}" ]; then
    _branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//')
    _sha=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    TAG="${_branch}-${_sha}"
else
    TAG="${IMAGE_TAG}"
fi
BUILT_IMAGES=()

# ── Image registry: stem → full tag ─────────────────────────────────────────
# Uses a temp file as a key-value store (compatible with bash 3.x on macOS).
_REGISTRY_FILE=$(mktemp)
trap 'rm -f "$_REGISTRY_FILE"' EXIT

_register_image() {
    local stem="$1"
    local full_tag="$2"
    echo "${stem}=${full_tag}" >> "$_REGISTRY_FILE"
    echo "[docker_build]   Registered: ${stem} → ${full_tag}"
}

_lookup_image() {
    local stem="$1"
    grep -m1 "^${stem}=" "$_REGISTRY_FILE" 2>/dev/null | cut -d= -f2- || true
}

# ── AR prefix (shared with NamingConvention.artifact_registry_repo) ──────────

_ar_prefix() {
    local host="${GCP_AR_HOST:-${AR_HOST:-}}"
    local project="${GCP_PROJECT_ID:-${GCP_PROJECT:-}}"
    local repo="${GCP_AR_REPO:-${AR_REPO:-}}"
    if [ -n "$host" ] && [ -n "$project" ] && [ -n "$repo" ]; then
        echo "${host}/${project}/${repo}"
    fi
}

# ── Image name resolution (delegates to Python for consistency) ──────────────

_resolve_image_name() {
    local pipeline_name="$1"
    local stem="$2"
    if [ -n "$pipeline_name" ]; then
        python -c "
from gcp_ml_framework.naming import NamingConvention
print(NamingConvention.docker_image_name(\"$pipeline_name\", \"$stem\"))
"
    else
        python -c "
from gcp_ml_framework.naming import NamingConvention
print(NamingConvention.docker_image_name(None, \"$stem\"))
"
    fi
}

_full_tag() {
    local name="$1"
    local prefix
    prefix=$(_ar_prefix)
    if [ -n "$prefix" ]; then
        echo "${prefix}/${name}:${TAG}"
    else
        echo "${name}:${TAG}"
    fi
}

# ── BASE_IMAGE resolution ────────────────────────────────────────────────────

_resolve_base_image() {
    local dockerfile="$1"

    local base_ref
    base_ref=$(grep -E '^\s*ARG\s+BASE_IMAGE=' "$dockerfile" | head -1 | sed 's/.*BASE_IMAGE=//' | tr -d '[:space:]')

    if [ -z "$base_ref" ]; then
        echo ""
        return
    fi

    # Look up in registry
    local resolved
    resolved=$(_lookup_image "$base_ref")
    if [ -n "$resolved" ]; then
        echo "$resolved"
        return
    fi

    # Not in registry — use as-is (external image or base-python:latest)
    echo "$base_ref"
}

_build() {
    local image_tag="$1"
    local dockerfile="$2"
    local context="$3"
    shift 3

    echo "[docker_build] Building ${image_tag}"
    if command -v docker &> /dev/null; then
        if [ "$PUSH" = true ] && [ -n "$(_ar_prefix)" ]; then
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

_build_with_base_resolve() {
    local stem="$1"
    local image_tag="$2"
    local dockerfile="$3"
    local context="$4"

    local base_image
    base_image=$(_resolve_base_image "$dockerfile")

    if [ -n "$base_image" ]; then
        echo "[docker_build]   Resolved BASE_IMAGE → ${base_image}"
        _build "$image_tag" "$dockerfile" "$context" \
            --build-arg "BASE_IMAGE=${base_image}"
    else
        _build "$image_tag" "$dockerfile" "$context"
    fi

    _register_image "$stem" "$image_tag"
}

# ── Seed registry with base-python (built separately via docker_build_base.sh) ─
_seed_base_python() {
    local prefix
    prefix=$(_ar_prefix)
    if [ -n "$prefix" ]; then
        _register_image "base-python" "${prefix}/base-python:latest"
    else
        _register_image "base-python" "base-python:latest"
    fi
}

# ── Layer 1: root-level default images ───────────────────────────────────────

_build_root_defaults() {
    for dockerfile in docker/*.Dockerfile; do
        [ -f "$dockerfile" ] || continue
        local stem
        stem=$(basename "$dockerfile" .Dockerfile)
        local image_name
        image_name=$(_resolve_image_name "" "$stem")
        local tag
        tag=$(_full_tag "$image_name")

        _build_with_base_resolve "$stem" "$tag" "$dockerfile" "."
    done
}

# ── Layer 2: pipeline-specific images ────────────────────────────────────────

_build_pipeline_images() {
    local pipeline_name="$1"
    local pipeline_docker_dir="docker/pipelines/${pipeline_name}"

    if [ ! -d "$pipeline_docker_dir" ]; then
        echo "[docker_build] ${pipeline_name}: no docker/pipelines/${pipeline_name}/ dir — using defaults"
        return
    fi

    for dockerfile in "${pipeline_docker_dir}"/*.Dockerfile; do
        [ -f "$dockerfile" ] || continue
        local stem
        stem=$(basename "$dockerfile" .Dockerfile)
        local image_name
        image_name=$(_resolve_image_name "$pipeline_name" "$stem")
        local tag
        tag=$(_full_tag "$image_name")

        _build_with_base_resolve "$stem" "$tag" "$dockerfile" "."
    done
}

# ── Layer 2: per-pipeline serving images ─────────────────────────────────────

_build_serving() {
    # Build a slim serving image for a pipeline directory.
    local pipeline_dir="$1"
    local pipeline_name
    pipeline_name=$(basename "$pipeline_dir")

    # Skip directories without a pipeline.py
    if [ ! -f "${pipeline_dir}/pipeline.py" ]; then
        return
    fi

    local dockerfile="docker/serving/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo "[docker_build] serving Dockerfile not found — skipping"
        return
    fi

    local image_name
    image_name=$(_slugify "$pipeline_name")-serving

    _build "$(_full_tag "$image_name")" "$dockerfile" "." \
        --build-arg "BASE_IMAGE=$(_full_tag base-python)"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo "[docker_build] Tag: ${TAG}"
    echo "[docker_build] Push: ${PUSH}"
    if [ -n "$PIPELINE_FILTER" ]; then
        echo "[docker_build] Pipeline filter: ${PIPELINE_FILTER}"
    fi
    echo ""

    # Seed base-python into the registry (built separately via docker_build_base.sh)
    _seed_base_python

    # Layer 1: root-level default images (train, serve, etc.)
    # These reference base-python:latest via ARG BASE_IMAGE
    _build_root_defaults

    # Layer 2: pipeline-specific images
    if [ -n "$PIPELINE_FILTER" ]; then
        _build_pipeline_images "$PIPELINE_FILTER"
    else
        for pipeline_docker_dir in docker/pipelines/*/; do
            [ -d "$pipeline_docker_dir" ] || continue
            local pipeline_name
            pipeline_name=$(basename "$pipeline_docker_dir")
            _build_pipeline_images "$pipeline_name"
        done
    fi

    # Layer 2: serving images
    for pipeline_dir in "${PIPELINES_DIR}"/*/; do
        _build_serving "$pipeline_dir"
    done

    echo ""
    echo "[docker_build] Done. Built ${#BUILT_IMAGES[@]} image(s)."
    for img in "${BUILT_IMAGES[@]}"; do
        echo "  - ${img}"
    done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
