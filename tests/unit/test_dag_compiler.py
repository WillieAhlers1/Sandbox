"""Unit tests for dag/compiler.py — DAGCompiler."""

import ast

import pytest

from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.compiler import DAGCompiler
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask


@pytest.fixture
def etl_dag_def():
    return (
        DAGBuilder(
            name="test_etl",
            schedule="30 7 * * *",
            description="Daily sales ETL",
            tags=["etl", "sales"],
        )
        .task(
            BQQueryTask(
                sql="SELECT * FROM `{bq_dataset}.raw_orders` WHERE dt = '{run_date}'",
                destination_table="staged_orders",
            ),
            name="extract",
        )
        .task(
            BQQueryTask(
                sql="SELECT category, SUM(amount) AS total FROM `{bq_dataset}.staged_orders` GROUP BY category",
                destination_table="daily_summary",
            ),
            name="transform",
        )
        .task(
            EmailTask(
                to=["team@co.com"],
                subject="[{namespace}] ETL done — {run_date}",
                body="Complete. Table: {bq_dataset}.daily_summary",
            ),
            name="notify",
        )
        .build()
    )


@pytest.fixture
def ml_dag_def():
    return (
        DAGBuilder(name="churn_pipeline", schedule="0 6 * * 1", tags=["ml"])
        .task(VertexPipelineTask(pipeline_name="churn_prediction"), name="run_ml")
        .task(
            EmailTask(to=["ml@co.com"], subject="ML done", body="done"),
            name="notify",
        )
        .build()
    )


class TestDAGCompiler:
    def test_render_returns_string(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert isinstance(source, str)

    def test_render_is_valid_python(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        # Must parse without SyntaxError
        ast.parse(source)

    def test_render_contains_dag_id(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        expected_dag_id = test_context.naming.dag_id("test_etl")
        assert expected_dag_id in source

    def test_render_contains_schedule(self, etl_dag_def, test_context):
        """DEV context renders schedule=None (no auto-scheduling in DEV)."""
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert "schedule=None" in source

    def test_render_contains_task_ids(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert "extract" in source
        assert "transform" in source
        assert "notify" in source

    def test_render_resolves_bq_dataset(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert test_context.bq_dataset in source
        # Framework template vars should be resolved
        assert "{bq_dataset}" not in source

    def test_render_converts_run_date_to_airflow_macro(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert "{{ ds }}" in source
        assert "{run_date}" not in source

    def test_render_contains_dependency_wiring(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        # Sequential deps: extract >> transform >> notify
        assert "extract >> transform" in source
        assert "transform >> notify" in source

    def test_render_contains_namespace_in_email(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert test_context.namespace in source

    def test_render_contains_tags(self, etl_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert "'etl'" in source
        assert "'sales'" in source

    def test_compile_writes_file(self, etl_dag_def, test_context, tmp_path):
        compiler = DAGCompiler(output_dir=tmp_path)
        path = compiler.compile(etl_dag_def, test_context)
        assert path.exists()
        assert path.suffix == ".py"
        # File content is valid Python
        ast.parse(path.read_text())

    def test_compile_filename(self, etl_dag_def, test_context, tmp_path):
        compiler = DAGCompiler(output_dir=tmp_path)
        path = compiler.compile(etl_dag_def, test_context)
        expected = test_context.naming.dag_id("test_etl") + ".py"
        assert path.name == expected

    def test_render_ml_dag_contains_vertex_operator(self, ml_dag_def, test_context):
        compiler = DAGCompiler()
        source = compiler.render(ml_dag_def, test_context)
        assert "CreatePipelineJobOperator" in source
        assert "churn_prediction" in source
        # Self-contained: no framework imports
        assert "gcp_ml_framework" not in source

    def test_render_parallel_deps(self, test_context):
        dag_def = (
            DAGBuilder(name="parallel", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3"), name="c", depends_on=["a", "b"])
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "[a, b] >> c" in source

    def test_render_no_description_uses_default(self, test_context):
        dag_def = (
            DAGBuilder(name="nodesc", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="t")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "nodesc" in source

    def test_render_dev_schedule_is_none(self, etl_dag_def, test_context):
        """DEV environments should compile with schedule=None to prevent backfill."""
        from gcp_ml_framework.config import GitState

        assert test_context.git_state == GitState.DEV
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        assert "schedule=None" in source
        # Original schedule should NOT appear as the active schedule
        assert "schedule='30 7 * * *'" not in source

    def test_render_staging_keeps_schedule(self, etl_dag_def):
        """STAGING environments should keep the declared schedule."""
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig, GitState
        from gcp_ml_framework.context import MLContext

        staging_config = FrameworkConfig(
            team="test",
            project="myproj",
            branch="main",
            gcp=GCPConfig(
                dev_project_id="my-gcp-dev",
                staging_project_id="my-gcp-staging",
                prod_project_id="my-gcp-prod",
            ),
        )
        staging_ctx = MLContext.from_config(staging_config)
        assert staging_ctx.git_state == GitState.STAGING

        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, staging_ctx)
        assert "schedule='30 7 * * *'" in source
        assert "schedule=None" not in source

    def test_render_prod_keeps_schedule(self, etl_dag_def):
        """PROD environments should keep the declared schedule."""
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig, GitState
        from gcp_ml_framework.context import MLContext

        prod_config = FrameworkConfig(
            team="test",
            project="myproj",
            branch="v1.0.0",
            gcp=GCPConfig(
                dev_project_id="my-gcp-dev",
                staging_project_id="my-gcp-staging",
                prod_project_id="my-gcp-prod",
            ),
        )
        prod_ctx = MLContext.from_config(prod_config)
        assert prod_ctx.git_state == GitState.PROD

        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, prod_ctx)
        assert "schedule='30 7 * * *'" in source
        assert "schedule=None" not in source

    def test_render_dev_no_is_paused_upon_creation(self, etl_dag_def, test_context):
        """DEV with schedule=None doesn't need is_paused_upon_creation."""
        compiler = DAGCompiler()
        source = compiler.render(etl_dag_def, test_context)
        # schedule=None means no auto-scheduling, so is_paused_upon_creation is unnecessary
        assert "is_paused_upon_creation" not in source
