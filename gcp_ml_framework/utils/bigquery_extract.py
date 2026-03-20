"""Reusable BigQuery extract logic — extracted from bigquery_extract component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_bigquery_extract(
    *,
    project: str,
    dataset: str,
    query: str,
    output_table: str,
    gcs_prefix: str,
    write_disposition: str,
    run_date: str,
    output_uri_path: str,
) -> None:
    """Execute a BQ query, materialise to a table, and export to GCS as Parquet."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    full_table = f"{project}.{dataset}.{output_table}"
    job_config = bigquery.QueryJobConfig(
        destination=full_table,
        write_disposition=write_disposition,
    )
    rendered_query = query.format(
        bq_dataset=dataset, gcs_prefix=gcs_prefix, run_date=run_date
    )
    logger.info(f"Running BQ query → {full_table}")
    client.query(rendered_query, job_config=job_config).result()

    output_uri = f"{gcs_prefix}extracts/{output_table}/*.parquet"
    extract_cfg = bigquery.ExtractJobConfig(destination_format="PARQUET")
    client.extract_table(full_table, output_uri, job_config=extract_cfg).result()
    logger.info(f"Exported to {output_uri}")

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_uri_path, "w") as f:
        f.write(output_uri)
