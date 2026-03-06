"""BigQuery utility helpers."""

from __future__ import annotations


def delete_bq_dataset(dataset: str, project: str) -> None:
    """Delete a BigQuery dataset and all its contents."""
    from google.cloud import bigquery  # type: ignore[import]

    client = bigquery.Client(project=project)
    client.delete_dataset(
        f"{project}.{dataset}",
        delete_contents=True,
        not_found_ok=True,
    )


def table_exists(project: str, dataset: str, table: str) -> bool:
    """Check if a BQ table exists. Only catches NotFound; other errors propagate."""
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery  # type: ignore[import]

    client = bigquery.Client(project=project)
    try:
        client.get_table(f"{project}.{dataset}.{table}")
        return True
    except NotFound:
        return False
