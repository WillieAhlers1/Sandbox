#!/usr/bin/env bash
# docker_build.sh — Build the full Docker image hierarchy and optionally push.
#
# Usage:
#   ./scripts/docker_build.sh [--push] [pipelines_dir]
#
# Image hierarchy (build order):
#   base-python → base-ml       → trainer images
#   base-python → component-base
#
# Environment variables:
#   AR_HOST     — Artifact Registry host (e.g. us-central1-docker.pkg.dev)
#   GCP_PROJECT — GCP project ID
#   AR_REPO     — AR repository name (e.g. dsci-examplechurn)
#   IMAGE_TAG   — Tag for all built images (default: latest)

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

TAG="${IMAGE_TAG:-latest}"
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
        docker build -t "${image_tag}" -f "${dockerfile}" "$@" "${context}"
        BUILT_IMAGES+=("${image_tag}")
    else
        echo "[docker_build] Docker not available — skipping"
    fi
}

_push_all() {
    if [ "$PUSH" = false ]; then
        return
    fi
    local prefix
    prefix=$(_ar_prefix)
    if [ -z "$prefix" ]; then
        echo "[docker_build] No AR env vars set — skipping push"
        return
    fi
    echo ""
    echo "[docker_build] Pushing ${#BUILT_IMAGES[@]} image(s) to Artifact Registry..."
    for img in "${BUILT_IMAGES[@]}"; do
        echo "[docker_build]   pushing ${img}"
        docker push "${img}"
    done
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

# ── Layer 1: base-ml + component-base (both depend on base-python) ───────────

_build_base_ml() {
    local dockerfile="docker/base/base-ml/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo "[docker_build] base-ml Dockerfile not found — skipping"
        return
    fi
    _build "$(_full_tag base-ml)" "$dockerfile" "docker/base/base-ml" \
        --build-arg "BASE_IMAGE=$(_full_tag base-python)"
}

_build_component_base() {
    local dockerfile="docker/base/component-base/Dockerfile"
    if [ ! -f "$dockerfile" ]; then
        echo "[docker_build] component-base Dockerfile not found — skipping"
        return
    fi
    _build "$(_full_tag component-base)" "$dockerfile" "docker/base/component-base" \
        --build-arg "BASE_IMAGE=$(_full_tag base-python)"
}

# ── Layer 2: trainer images (depend on base-ml) ─────────────────────────────

_generate_dockerfile() {
    local trainer_dir="$1"
    local dockerfile="${trainer_dir}/Dockerfile.generated"
    local base_image
    base_image=$(_full_tag base-ml)

    cat > "${dockerfile}" <<DOCKER_EOF
FROM ${base_image}

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY train.py /app/train.py

ENTRYPOINT ["python", "/app/train.py"]
DOCKER_EOF

    echo "[docker_build] Generated ${dockerfile}"
}

_build_trainers() {
    local found=0
    for pipeline_dir in "${PIPELINES_DIR}"/*/; do
        local trainer_dir="${pipeline_dir}trainer"
        if [ -f "${trainer_dir}/train.py" ] && [ -f "${trainer_dir}/requirements.txt" ]; then
            local pipeline_name
            pipeline_name=$(basename "${pipeline_dir}")
            found=1

            if [ ! -f "${trainer_dir}/Dockerfile" ]; then
                _generate_dockerfile "${trainer_dir}"
            fi

            local slug
            slug=$(_slugify "${pipeline_name}")
            local dockerfile
            if [ -f "${trainer_dir}/Dockerfile" ]; then
                dockerfile="${trainer_dir}/Dockerfile"
            else
                dockerfile="${trainer_dir}/Dockerfile.generated"
            fi
            _build "$(_full_tag "${slug}-trainer")" "$dockerfile" "$trainer_dir"
        fi
    done

    if [ "$found" -eq 0 ]; then
        echo "[docker_build] No pipelines with trainer/ directories found."
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo "[docker_build] Tag: ${TAG}"
    echo "[docker_build] Push: ${PUSH}"
    echo ""

    # Layer 0: foundation
    _build_base_python

    # Layer 1: SDK images (both depend on base-python)
    _build_base_ml
    _build_component_base

    # Layer 2: per-pipeline trainer images (depend on base-ml)
    _build_trainers

    # Push all built images if --push was given
    _push_all

    echo ""
    echo "[docker_build] Done. Built ${#BUILT_IMAGES[@]} image(s)."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
