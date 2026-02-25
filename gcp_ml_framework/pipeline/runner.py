"""
Pipeline runners.

LocalRunner   — runs pipeline steps sequentially using local stubs (no GCP).
VertexRunner  — submits a compiled KFP YAML to Vertex AI Pipelines.
"""

from __future__ import annotations

import duckdb
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition


class LocalRunner:
    """
    Execute a pipeline locally by calling each component's local_run() method
    in topological order (linear for now — steps run sequentially).

    GCS/BQ/Vertex SDK calls are replaced by DuckDB + pandas + temp file stubs.
    Useful for:
    - Local iteration without GCP access
    - Unit and integration tests
    - CI compile-only checks (--dry-run)

    Seed data
    ---------
    SQL-based components (BigQueryExtract, BQTransform) query DuckDB by the
    branch-namespaced table name, e.g. ``"dsci_churn_pred_main"."raw_events"``.
    Two mechanisms populate those tables automatically:

    1. **Seed files** — place ``seeds/<table_name>.csv`` (or ``.parquet``) in the
       pipeline directory.  ``_seed_duckdb()`` loads them into DuckDB before the
       first step runs.

    2. **Intermediate registration** — after each step ``_register_output()``
       registers the step's Parquet output as a DuckDB table so that downstream
       SQL transforms can reference it by name.
    """

    def __init__(self, context: "MLContext", seeds_dir: Path | None = None) -> None:
        self._ctx = context
        self._seeds_dir = Path(seeds_dir) if seeds_dir else None
        # Single persistent in-memory connection shared across all steps so that
        # seeded tables and intermediate outputs are visible to every local_run().
        self._conn = duckdb.connect()

    def _seed_duckdb(self) -> None:
        """Pre-populate DuckDB with fixture data from the seeds/ directory.

        Any ``.csv`` or ``.parquet`` file in ``seeds_dir`` is loaded as a table
        named ``<bq_dataset>.<stem>`` so that ingestion SQL can reference it.
        """
        if not self._seeds_dir or not self._seeds_dir.exists():
            return

        dataset = self._ctx.bq_dataset
        self._conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')

        for seed_file in sorted(self._seeds_dir.iterdir()):
            if seed_file.suffix == ".parquet":
                reader = f"read_parquet('{seed_file.as_posix()}')"
            elif seed_file.suffix == ".csv":
                reader = f"read_csv_auto('{seed_file.as_posix()}')"
            else:
                continue

            table_name = seed_file.stem
            self._conn.sql(
                f'CREATE OR REPLACE TABLE "{dataset}"."{table_name}" '
                f"AS SELECT * FROM {reader}"
            )
            print(f"[local]   seeded  {dataset}.{table_name}  ({seed_file.name})")

    def _register_output(self, component: Any, result: Any) -> None:
        """Register a step's Parquet output as a DuckDB table.

        This makes intermediate outputs (e.g. ``churn_training_raw``) queryable
        by name in downstream SQL transforms without any extra configuration.
        """
        if not isinstance(result, str) or not result.endswith(".parquet"):
            return
        if not hasattr(component, "output_table"):
            return

        dataset = self._ctx.bq_dataset
        table_name = component.output_table
        self._conn.sql(
            f'CREATE OR REPLACE TABLE "{dataset}"."{table_name}" '
            f"AS SELECT * FROM read_parquet('{result}')"
        )
        print(f"[local]   registered  {dataset}.{table_name}")

    def print_plan(self, pipeline_def: "PipelineDefinition") -> None:
        print(f"\nPipeline: {pipeline_def.name!r}  (schedule={pipeline_def.schedule!r})")
        print(f"{'Step':<30} {'Stage':<20} {'Component'}")
        print("-" * 70)
        for step in pipeline_def.steps:
            print(f"  {step.name:<28} {step.stage:<20} {step.component.__class__.__name__}")
        print()

    def run(
        self,
        pipeline_def: "PipelineDefinition",
        run_date: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Execute all steps in order. Each step receives the output of the previous
        step as its primary input (where applicable).

        Returns a dict of {step_name: output}.
        """
        self._seed_duckdb()

        outputs: dict[str, Any] = {}
        prev_output: Any = None

        for step in pipeline_def.steps:
            if dry_run:
                print(f"[dry-run] {step.name} ({step.component.__class__.__name__})")
                continue

            print(f"[local] {step.name} ({step.component.__class__.__name__}) ...")
            try:
                kwargs: dict[str, Any] = {"run_date": run_date, "db_conn": self._conn}
                # Wire the previous step's output as input to the next step
                if prev_output is not None:
                    kwargs["input_path"] = prev_output

                result = step.component.local_run(self._ctx, **kwargs)
                outputs[step.name] = result
                prev_output = result
                self._register_output(step.component, result)
                print(f"[local]   → {result}")
            except Exception as exc:
                print(f"[local]   FAILED: {exc}")
                raise

        return outputs


class VertexRunner:
    """
    Submit a compiled KFP pipeline YAML to Vertex AI Pipelines.
    """

    def __init__(self, context: "MLContext") -> None:
        self._ctx = context

    def submit(
        self,
        compiled_path: Path,
        pipeline_name: str,
        parameter_values: dict | None = None,
        enable_caching: bool = True,
        sync: bool = False,
    ) -> Any:
        """
        Submit the pipeline and optionally wait for completion.

        Returns the aiplatform.PipelineJob object.
        """
        try:
            from google.cloud import aiplatform  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-aiplatform is required. Install with: pip install google-cloud-aiplatform"
            ) from exc

        aiplatform.init(
            project=self._ctx.gcp_project,
            location=self._ctx.region,
            staging_bucket=f"gs://{self._ctx.naming.gcs_bucket}",
        )

        job = aiplatform.PipelineJob(
            display_name=self._ctx.naming.vertex_pipeline_display_name(pipeline_name),
            template_path=str(compiled_path),
            pipeline_root=self._ctx.naming.gcs_pipeline_root(pipeline_name),
            parameter_values=parameter_values or {},
            enable_caching=enable_caching,
        )
        job.submit(service_account=self._ctx.service_account_email)
        if sync:
            job.wait()
        return job
