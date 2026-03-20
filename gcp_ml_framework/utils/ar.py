"""Artifact Registry utility helpers."""

from __future__ import annotations


def ensure_image_tag(
    image_uri: str,
    project: str,
) -> bool:
    """Ensure a Docker image tag exists in Artifact Registry.

    If the exact tag doesn't exist, finds the same image with any tag
    matching the same branch prefix and adds the required tag as an alias.

    Returns True if the tag exists (or was created), False if no source
    image was found (user needs to run docker_build.sh).
    """
    import subprocess

    # Parse image URI: host/project/repo/image:tag
    parts = image_uri.split(":")
    if len(parts) != 2:
        return False
    image_path, target_tag = parts

    # Check if the exact tag already exists
    result = subprocess.run(
        ["gcloud", "artifacts", "docker", "images", "list",
         image_path, "--include-tags", "--format=value(tags)",
         "--project", project],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            tags = line.split(",")
            if target_tag in tags:
                return True  # Tag already exists

    # Tag doesn't exist. Find any existing image for this path
    # and add the target tag as an alias.
    # Extract branch prefix from target tag (e.g., "os-experimental" from "os-experimental-7cee1bb")
    branch_prefix = "-".join(target_tag.rsplit("-", 1)[:-1])  # strip the SHA suffix

    # Find an existing tag with the same branch prefix
    source_tag = None
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            tags = line.split(",")
            for tag in tags:
                if tag.startswith(branch_prefix + "-") or tag == "latest":
                    source_tag = tag
                    break
            if source_tag:
                break

    if not source_tag:
        return False  # No source image found — need docker_build.sh

    # Re-tag: add the target tag to the existing image
    subprocess.run(
        ["gcloud", "artifacts", "docker", "tags", "add",
         f"{image_path}:{source_tag}",
         f"{image_path}:{target_tag}"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return True
