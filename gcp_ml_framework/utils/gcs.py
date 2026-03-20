"""GCS utility helpers."""

from __future__ import annotations

from pathlib import Path


def upload_file(local_path: Path, gcs_uri: str, project: str) -> None:
    """Upload a local file to GCS."""
    from google.cloud import storage  # type: ignore[import]

    client = storage.Client(project=project)
    without_scheme = gcs_uri[5:]
    bucket_name, _, blob_name = without_scheme.partition("/")
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path))


def delete_gcs_prefix(prefix: str, project: str) -> None:
    """Delete all objects under a GCS prefix (gs://bucket/prefix/)."""
    from google.cloud import storage  # type: ignore[import]

    client = storage.Client(project=project)
    without_scheme = prefix[5:]
    bucket_name, _, prefix_path = without_scheme.partition("/")
    bucket = client.bucket(bucket_name)
    blobs = list(client.list_blobs(bucket_name, prefix=prefix_path))
    if blobs:
        bucket.delete_blobs(blobs)


def copy_gcs_prefix(
    src_prefix: str,
    dst_prefix: str,
    src_project: str,
    dst_project: str,
) -> None:
    """Copy all objects from src_prefix to dst_prefix (cross-project safe)."""
    from google.cloud import storage  # type: ignore[import]

    src_client = storage.Client(project=src_project)
    dst_client = storage.Client(project=dst_project)

    src_without = src_prefix[5:]
    src_bucket_name, _, src_path = src_without.partition("/")
    dst_without = dst_prefix[5:]
    dst_bucket_name, _, dst_path = dst_without.partition("/")

    src_bucket = src_client.bucket(src_bucket_name)
    dst_bucket = dst_client.bucket(dst_bucket_name)

    for blob in src_client.list_blobs(src_bucket_name, prefix=src_path):
        rel = blob.name[len(src_path):]
        dst_blob_name = dst_path + rel
        src_bucket.copy_blob(blob, dst_bucket, dst_blob_name)
