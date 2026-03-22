"""Resolve Docker image names using the framework's NamingConvention.

Called by docker_build.sh to ensure bash and Python use identical naming logic.
The NamingConvention.docker_image_name() method is the single source of truth.

Usage:
    python -m scripts.resolve_image <pipeline_name_or_empty> <dockerfile_stem>

    # Root-level Dockerfile (no pipeline prefix):
    python -m scripts.resolve_image "" train
    # → train

    # Pipeline-specific Dockerfile:
    python -m scripts.resolve_image house_price house_price_base
    # → house-price--house-price-base
"""

import sys

from gcp_ml_framework.naming import NamingConvention


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <pipeline_name|''> <dockerfile_stem>", file=sys.stderr)
        sys.exit(1)

    pipeline_name = sys.argv[1] or None
    dockerfile_stem = sys.argv[2]

    print(NamingConvention.docker_image_name(pipeline_name, dockerfile_stem))


if __name__ == "__main__":
    main()
