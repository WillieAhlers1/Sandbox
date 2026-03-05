"""
DAGLocalRunner — local execution engine for DAGBuilder-defined workflows.

Executes DAG tasks sequentially in topological order using DuckDB for
BigQuery substitution and console printing for email tasks.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.dag.builder import DAGDefinition


class DAGLocalRunner:
    """
    Execute a DAGDefinition locally by running each task in topological order.

    Task type handling:
    - BQQueryTask → run SQL via DuckDB (with bq_to_duckdb translation)
    - EmailTask → print to console
    - VertexPipelineTask → run the contained pipeline via pipeline LocalRunner
    """

    def __init__(
        self,
        context: MLContext,
        seeds_dir: Path | None = None,
        pipeline_dir: Path | None = None,
    ) -> None:
        self._ctx = context
        self._seeds_dir = Path(seeds_dir) if seeds_dir else None
        self._pipeline_dir = Path(pipeline_dir) if pipeline_dir else None
        self._conn = duckdb.connect()

    def _seed_duckdb(self) -> None:
        """Pre-populate DuckDB with fixture data from the seeds/ directory."""
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
            print(f"[dag-local]   seeded  {dataset}.{table_name}  ({seed_file.name})")

    def run(
        self,
        dag_def: DAGDefinition,
        run_date: str = "",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute all tasks in topological order. Returns {task_name: result}."""
        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
        from gcp_ml_framework.dag.tasks.email import EmailTask
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        run_date = run_date or datetime.date.today().isoformat()

        self._seed_duckdb()

        outputs: dict[str, Any] = {}
        for dag_task in dag_def.topological_order():
            if dry_run:
                print(f"[dag-dry-run] {dag_task.name} ({dag_task.task.task_type})")
                continue

            print(f"[dag-local] {dag_task.name} ({dag_task.task.task_type}) ...")
            task = dag_task.task

            if isinstance(task, BQQueryTask):
                result = self._run_bq_query(task, run_date)
            elif isinstance(task, EmailTask):
                result = self._run_email(task, run_date)
            elif isinstance(task, VertexPipelineTask):
                result = self._run_vertex_pipeline(task, run_date)
            else:
                raise TypeError(f"Unknown task type: {type(task).__name__}")

            outputs[dag_task.name] = result
            print(f"[dag-local]   → done")

        return outputs

    def _run_bq_query(self, task: Any, run_date: str) -> str:
        """Execute a BQQueryTask via DuckDB."""
        from gcp_ml_framework.utils.sql_compat import bq_to_duckdb

        # Load SQL content (inline or from file)
        sql = task._load_sql_content(self._pipeline_dir)

        # Resolve framework template variables for local execution
        sql = sql.replace("{bq_dataset}", self._ctx.bq_dataset)
        sql = sql.replace("{gcs_prefix}", self._ctx.gcs_prefix)
        sql = sql.replace("{namespace}", self._ctx.namespace)
        sql = sql.replace("{run_date}", run_date)

        # Translate BQ SQL → DuckDB SQL
        sql = bq_to_duckdb(sql)

        # If there's a destination table, wrap in CREATE TABLE
        if task.destination_table:
            dataset = self._ctx.bq_dataset
            self._conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
            self._conn.sql(
                f'CREATE OR REPLACE TABLE "{dataset}"."{task.destination_table}" '
                f"AS {sql}"
            )
            print(f"[dag-local]   wrote → {dataset}.{task.destination_table}")
            return f"{dataset}.{task.destination_table}"

        # No destination — just execute
        result = self._conn.sql(sql)
        return "executed"

    def _run_email(self, task: Any, run_date: str) -> str:
        """Print email to console instead of sending."""
        subject = task.subject
        body = task.body

        # Resolve template vars for local display
        for var, val in [
            ("{namespace}", self._ctx.namespace),
            ("{bq_dataset}", self._ctx.bq_dataset),
            ("{gcs_prefix}", self._ctx.gcs_prefix),
            ("{run_date}", run_date),
        ]:
            subject = subject.replace(var, val)
            body = body.replace(var, val)

        print(f"[dag-local]   📧 To: {', '.join(task.to)}")
        print(f"[dag-local]   📧 Subject: {subject}")
        print(f"[dag-local]   📧 Body: {body}")
        return "email_printed"

    def _run_vertex_pipeline(self, task: Any, run_date: str) -> str:
        """Run a VertexPipelineTask locally by executing its pipeline via LocalRunner."""
        pipeline_name = task.pipeline_name
        print(f"[dag-local]   Running Vertex pipeline '{pipeline_name}' locally...")

        from gcp_ml_framework.pipeline.runner import LocalRunner

        # Prefer the inline pipeline object (no directory lookup needed)
        if task.pipeline is not None:
            runner = LocalRunner(self._ctx, seeds_dir=None)
            # Share the DuckDB connection so tables from the DAG are visible
            runner._conn = self._conn
            runner.run(task.pipeline, run_date=run_date)
            return f"vertex_pipeline:{pipeline_name}:completed"

        # Fallback: discover pipeline.py by name on disk
        pipelines_root = Path("pipelines")
        if self._pipeline_dir:
            pipelines_root = self._pipeline_dir.parent

        pipeline_dir = pipelines_root / pipeline_name
        pipeline_py = pipeline_dir / "pipeline.py"

        if pipeline_py.exists():
            import importlib.util
            import sys

            spec = importlib.util.spec_from_file_location(
                f"_vp_{pipeline_name}", pipeline_py
            )
            mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            sys.modules[f"_vp_{pipeline_name}"] = mod
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            pipeline_def = mod.pipeline

            seeds_dir = pipeline_dir / "seeds"
            runner = LocalRunner(
                self._ctx,
                seeds_dir=seeds_dir if seeds_dir.exists() else None,
            )
            runner._conn = self._conn
            runner.run(pipeline_def, run_date=run_date)
            return f"vertex_pipeline:{pipeline_name}:completed"

        print(f"[dag-local]   (no pipeline.py found for '{pipeline_name}', skipping)")
        return f"vertex_pipeline:{pipeline_name}:skipped"
