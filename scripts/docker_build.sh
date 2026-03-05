#!/usr/bin/env bash
# docker_build.sh — Auto-generate Dockerfiles and build trainer images.
#
# Usage:
#   ./scripts/docker_build.sh [pipelines_dir]
#
# Scans pipelines/*/trainer/ for directories containing train.py + requirements.txt.
# If no Dockerfile exists, auto-generates one using the base-ml image.

set -euo pipefail

PIPELINES_DIR="${1:-pipelines}"

_generate_dockerfile() {
    local trainer_dir="$1"
    local dockerfile="${trainer_dir}/Dockerfile.generated"

    cat > "${dockerfile}" <<'DOCKER_EOF'
FROM base-ml:latest

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

    local image_tag="${pipeline_name}-trainer:latest"
    echo "[docker_build] Building ${image_tag} from ${dockerfile}"

    if command -v docker &> /dev/null; then
        docker build -t "${image_tag}" -f "${dockerfile}" "${trainer_dir}"
    else
        echo "[docker_build] Docker not available — skipping build for ${image_tag}"
    fi
}

# Main: scan pipelines for trainer directories
main() {
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
