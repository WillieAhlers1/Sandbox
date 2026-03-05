#!/usr/bin/env bash
# docker_build.sh — Auto-generate Dockerfiles and build trainer images.
#
# Usage:
#   ./scripts/docker_build.sh [pipelines_dir]
#
# Scans pipelines/*/trainer/ for directories containing train.py + requirements.txt.
# If no Dockerfile exists, auto-generates one using the base-ml image.
#
# Environment variables (for AR-hosted base images):
#   AR_HOST         — Artifact Registry host (e.g. us-central1-docker.pkg.dev)
#   GCP_PROJECT     — GCP project ID
#   AR_REPO         — AR repository name (e.g. dsci-examplechurn)
#   BASE_IMAGE_TAG  — Tag for the base-ml image (default: latest)
#   IMAGE_TAG       — Tag for the built trainer image (e.g. main-abc1234)

set -euo pipefail

PIPELINES_DIR="${1:-pipelines}"

_resolve_base_image() {
    # Returns the full base image reference.
    # With AR env vars: us-central1-docker.pkg.dev/proj/repo/base-ml:tag
    # Without: base-ml:latest (local development)
    if [ -n "${AR_HOST:-}" ] && [ -n "${GCP_PROJECT:-}" ] && [ -n "${AR_REPO:-}" ]; then
        local tag="${BASE_IMAGE_TAG:-latest}"
        echo "${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/base-ml:${tag}"
    else
        echo "base-ml:latest"
    fi
}

_slugify() {
    # Lowercase, replace non-alphanumeric runs with hyphens, strip leading/trailing
    echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//'
}

_generate_dockerfile() {
    local trainer_dir="$1"
    local dockerfile="${trainer_dir}/Dockerfile.generated"
    local base_image
    base_image=$(_resolve_base_image)

    cat > "${dockerfile}" <<DOCKER_EOF
FROM ${base_image}

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY train.py /app/train.py

ENTRYPOINT ["python", "/app/train.py"]
DOCKER_EOF

    echo "[docker_build] Generated ${dockerfile}"
}

_build_image() {
    local pipeline_name="$1"
    local trainer_dir="$2"
    local dockerfile

    # Use existing Dockerfile if present, otherwise generate one
    if [ -f "${trainer_dir}/Dockerfile" ]; then
        dockerfile="${trainer_dir}/Dockerfile"
    elif [ -f "${trainer_dir}/Dockerfile.generated" ]; then
        dockerfile="${trainer_dir}/Dockerfile.generated"
    else
        _generate_dockerfile "${trainer_dir}"
        dockerfile="${trainer_dir}/Dockerfile.generated"
    fi

    # Derive image tag: with AR vars use full AR URI, otherwise local tag
    local slug
    slug=$(_slugify "${pipeline_name}")
    local image_name="${slug}-trainer"

    local image_tag
    if [ -n "${AR_HOST:-}" ] && [ -n "${GCP_PROJECT:-}" ] && [ -n "${AR_REPO:-}" ]; then
        local tag="${IMAGE_TAG:-latest}"
        image_tag="${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/${image_name}:${tag}"
    else
        image_tag="${image_name}:latest"
    fi

    echo "[docker_build] Building ${image_tag} from ${dockerfile}"

    if command -v docker &> /dev/null; then
        docker build -t "${image_tag}" -f "${dockerfile}" "${trainer_dir}"
    else
        echo "[docker_build] Docker not available — skipping build for ${image_tag}"
    fi
}

_build_component_base() {
    # Build the component-base image with all GCP SDK + data dependencies.
    # Components use this image to skip runtime pip installs.
    local dockerfile="docker/base/component-base/Dockerfile"
    if [ ! -f "${dockerfile}" ]; then
        echo "[docker_build] component-base Dockerfile not found — skipping"
        return
    fi

    local image_tag
    if [ -n "${AR_HOST:-}" ] && [ -n "${GCP_PROJECT:-}" ] && [ -n "${AR_REPO:-}" ]; then
        local tag="${BASE_IMAGE_TAG:-latest}"
        image_tag="${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/component-base:${tag}"
    else
        image_tag="component-base:latest"
    fi

    echo "[docker_build] Building ${image_tag} from ${dockerfile}"

    if command -v docker &> /dev/null; then
        docker build -t "${image_tag}" -f "${dockerfile}" "docker/base/component-base"
    else
        echo "[docker_build] Docker not available — skipping build for ${image_tag}"
    fi
}

# Main: scan pipelines for trainer directories
main() {
    # Build the shared component-base image first
    _build_component_base

    local found=0
    for pipeline_dir in "${PIPELINES_DIR}"/*/; do
        local trainer_dir="${pipeline_dir}trainer"
        if [ -f "${trainer_dir}/train.py" ] && [ -f "${trainer_dir}/requirements.txt" ]; then
            local pipeline_name
            pipeline_name=$(basename "${pipeline_dir}")
            found=1

            # Generate Dockerfile if none exists
            if [ ! -f "${trainer_dir}/Dockerfile" ]; then
                _generate_dockerfile "${trainer_dir}"
            fi

            _build_image "${pipeline_name}" "${trainer_dir}"
        fi
    done

    if [ "${found}" -eq 0 ]; then
        echo "[docker_build] No pipelines with trainer/ directories found."
    fi
}

# Only run main if script is executed directly (not sourced)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
