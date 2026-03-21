"""Reusable BQ transform logic — extracted from bq_transform component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_bq_transform(
    *,
    project: str,
    dataset: str,
    sql: str,
    output_table: str,
    write_disposition: str,
    run_date: str,
    output_uri_path: str,
) -> None:
    """Execute a SQL transformation in BigQuery and write to a destination table."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    rendered = sql.format(
        bq_dataset=dataset,
        run_date=run_date,
    )
    dest = f"{project}.{dataset}.{output_table}"
    cfg = bigquery.QueryJobConfig(
        destination=dest,
        write_disposition=write_disposition,
        use_legacy_sql=False,
    )
    logger.info(f"Running BQ transform → {dest}")
    client.query(rendered, job_config=cfg).result()

    if output_uri_path:
        Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_uri_path, "w") as f:
            f.write(dest)
