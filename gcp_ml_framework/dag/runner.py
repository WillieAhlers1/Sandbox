"""
DAG runners — local execution and Composer triggering.

DAGLocalRunner: executes DAG tasks sequentially in topological order using
DuckDB for BigQuery substitution and console printing for email tasks.

ComposerRunner: triggers an already-deployed DAG on Cloud Composer via the
Airflow REST API.
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
                f'CREATE OR REPLACE TABLE "{dataset}"."{table_name}" AS SELECT * FROM {reader}'
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
                f'CREATE OR REPLACE TABLE "{dataset}"."{task.destination_table}" AS {sql}'
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

            spec = importlib.util.spec_from_file_location(f"_vp_{pipeline_name}", pipeline_py)
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


class ComposerRunner:
    """
    Trigger an already-deployed DAG on Cloud Composer via the Airflow REST API.

    Usage:
        runner = ComposerRunner(context)
        result = runner.trigger_dag("sales_analytics", run_date="2026-03-01")
    """

    def __init__(self, context: MLContext) -> None:
        self._ctx = context
        self._airflow_uri: str | None = None

    def resolve_dag_id(self, pipeline_name: str) -> str:
        """Derive the Composer DAG ID from the pipeline name and context."""
        return self._ctx.naming.dag_id(pipeline_name)

    def _get_airflow_uri(self) -> str:
        """Discover the Airflow webserver URI from the Composer environment."""
        if self._airflow_uri:
            return self._airflow_uri

        import subprocess

        # Composer env name follows Terraform convention: {team}-{project}-{env}
        # e.g. "dsci-examplechurn-dev"
        env_suffix = self._ctx.git_state.value.lower()
        env_name = f"{self._ctx.naming.team}-{self._ctx.naming.project}-{env_suffix}"
        result = subprocess.run(
            [
                "gcloud",
                "composer",
                "environments",
                "describe",
                env_name,
                "--location",
                self._ctx.region,
                "--project",
                self._ctx.gcp_project,
                "--format",
                "value(config.airflowUri)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self._airflow_uri = result.stdout.strip()
        return self._airflow_uri

    def _build_trigger_url(self, dag_id: str) -> str:
        """Build the Airflow REST API URL for triggering a DAG run."""
        base = self._get_airflow_uri()
        return f"{base}/api/v1/dags/{dag_id}/dagRuns"

    def _trigger_dag_run(self, dag_id: str, logical_date: str) -> dict[str, Any]:
        """Trigger a DAG run via gcloud composer CLI.

        Uses `gcloud composer environments run ... dags trigger` which handles
        authentication transparently for all credential types (user, SA, metadata).
        """
        import subprocess

        env_suffix = self._ctx.git_state.value.lower()
        env_name = f"{self._ctx.naming.team}-{self._ctx.naming.project}-{env_suffix}"

        try:
            result = subprocess.run(
                [
                    "gcloud",
                    "composer",
                    "environments",
                    "run",
                    env_name,
                    "--location",
                    self._ctx.region,
                    "--project",
                    self._ctx.gcp_project,
                    "dags",
                    "trigger",
                    "--",
                    dag_id,
                    "-e",
                    logical_date,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            # Composer 3's executeAirflowCommand API can hang while fetching
            # output even though the trigger was dispatched. Treat as success.
            print(f"[composer] Warning: trigger command timed out (trigger likely accepted)")
            return {
                "dag_run_id": f"manual__{logical_date}",
                "state": "queued",
                "output": "trigger dispatched (output fetch timed out)",
            }
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            # Composer 3 often returns non-zero even when the trigger succeeded
            # (e.g., MalformedJsonException in output parsing). Check stderr.
            if "trigger" in stderr.lower() or "already exists" in stderr.lower():
                print(f"[composer] Warning: trigger returned non-zero but may have succeeded")
                return {
                    "dag_run_id": f"manual__{logical_date}",
                    "state": "queued",
                    "output": stderr.strip(),
                }
            raise RuntimeError(
                f"Failed to trigger DAG '{dag_id}':\n{stderr}"
            ) from e

        # Parse the output for run info
        output = result.stdout + result.stderr
        return {
            "dag_run_id": f"manual__{logical_date}",
            "state": "queued",
            "output": output.strip(),
        }

    def unpause_dag(self, dag_id: str) -> None:
        """Unpause a DAG so the scheduler processes its task instances.

        Best-effort — Composer 3's executeAirflowCommand API can return
        transient 500 errors. A failure here should not block the trigger.
        """
        import subprocess

        env_suffix = self._ctx.git_state.value.lower()
        env_name = f"{self._ctx.naming.team}-{self._ctx.naming.project}-{env_suffix}"

        try:
            subprocess.run(
                [
                    "gcloud",
                    "composer",
                    "environments",
                    "run",
                    env_name,
                    "--location",
                    self._ctx.region,
                    "--project",
                    self._ctx.gcp_project,
                    "dags",
                    "unpause",
                    "--",
                    dag_id,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            print(f"[composer] DAG '{dag_id}' unpaused")
        except Exception as e:
            print(f"[composer] Warning: could not unpause DAG '{dag_id}': {e}")

    def trigger_dag(self, pipeline_name: str, run_date: str = "") -> dict[str, Any]:
        """Trigger a DAG run on Composer. Returns the Airflow API response."""
        run_date = run_date or datetime.date.today().isoformat()
        dag_id = self.resolve_dag_id(pipeline_name)

        print(f"[composer] Triggering DAG '{dag_id}' for date {run_date}...")
        result = self._trigger_dag_run(dag_id, run_date)
        print(f"[composer] DAG run triggered: {result.get('dag_run_id', 'unknown')}")
        print(f"[composer] State: {result.get('state', 'unknown')}")
        return result
