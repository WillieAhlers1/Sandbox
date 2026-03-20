"""Reusable GCS extract logic — extracted from gcs_extract component."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from loguru import logger


def run_gcs_extract(
    *,
    source_uri: str,
    gcs_prefix: str,
    destination_folder: str,
    project: str,
    output_uri_path: str,
) -> None:
    """Copy files from a GCS source URI to the branch staging prefix."""
    from google.cloud import storage

    client = storage.Client(project=project)
    dest_prefix = f"{gcs_prefix}staging/{destination_folder}/"

    without_scheme = source_uri[5:]
    src_bucket_name, _, src_path = without_scheme.partition("/")
    src_bucket = client.bucket(src_bucket_name)

    pattern = src_path if "*" in src_path else src_path + "/*"
    blobs = list(client.list_blobs(src_bucket_name, prefix=src_path.split("*")[0]))

    dest_bucket_name = gcs_prefix[5:].split("/")[0]
    dest_bucket = client.bucket(dest_bucket_name)
    dest_prefix_path = "/".join(gcs_prefix[5:].split("/")[1:]) + f"staging/{destination_folder}/"

    for blob in blobs:
        if fnmatch.fnmatch(blob.name, pattern.replace(src_path.split("*")[0], "")):
            dest_blob_name = dest_prefix_path + blob.name.split("/")[-1]
            src_bucket.copy_blob(blob, dest_bucket, dest_blob_name)

    logger.info(f"Copied {len(blobs)} blobs to {dest_prefix}")

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_uri_path, "w") as f:
        f.write(dest_prefix)
