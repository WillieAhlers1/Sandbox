"""Phase 2 TDD tests — DAG local runner, Docker auto-gen, use cases."""

import ast
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.dag.builder import DAGBuilder, DAGDefinition
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask


# ═══════════════════════════════════════════════════════════════════════
# 2.1 Docker auto-generation + TrainModel optional image
# ═══════════════════════════════════════════════════════════════════════


class TestDockerAutoGeneration:
    def test_base_python_dockerfile_exists(self):
        path = Path("docker/base/base-python/Dockerfile")
        assert path.exists(), f"Missing {path}"

    def test_base_ml_dockerfile_exists(self):
        path = Path("docker/base/base-ml/Dockerfile")
        assert path.exists(), f"Missing {path}"

    def test_base_python_dockerfile_uses_python311(self):
        content = Path("docker/base/base-python/Dockerfile").read_text()
        assert "python:3.11-slim" in content

    def test_base_ml_dockerfile_references_base_python(self):
        content = Path("docker/base/base-ml/Dockerfile").read_text()
        assert "base-python" in content

    def test_base_ml_dockerfile_installs_ml_packages(self):
        content = Path("docker/base/base-ml/Dockerfile").read_text()
        for pkg in ["scikit-learn", "pandas", "numpy"]:
            assert pkg in content, f"base-ml Dockerfile missing {pkg}"

    def test_docker_build_script_exists(self):
        path = Path("scripts/docker_build.sh")
        assert path.exists(), f"Missing {path}"

    def test_docker_build_script_is_executable(self):
        path = Path("scripts/docker_build.sh")
        assert os.access(path, os.X_OK), f"{path} is not executable"

    def test_docker_build_script_auto_generates_dockerfile(self, tmp_path):
        """Script generates Dockerfile when only train.py + requirements.txt exist."""
        # Create a temp pipeline with trainer/train.py + requirements.txt, no Dockerfile
        trainer_dir = tmp_path / "pipelines" / "test_pipe" / "trainer"
        trainer_dir.mkdir(parents=True)
        (trainer_dir / "train.py").write_text("print('hello')")
        (trainer_dir / "requirements.txt").write_text("scikit-learn>=1.5\n")

        # Source the script functions and call _generate_dockerfile
        import subprocess

        result = subprocess.run(
            ["bash", "-c", f"""
                source scripts/docker_build.sh
                _generate_dockerfile "{trainer_dir}"
            """],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Script failed: {result.stderr}"
        generated = trainer_dir / "Dockerfile.generated"
        assert generated.exists(), "Dockerfile.generated was not created"
        content = generated.read_text()
        assert "base-ml" in content
        assert "requirements.txt" in content


class TestTrainModelOptionalImage:
    def test_train_model_no_image_allowed(self):
        """TrainModel can be created without trainer_image."""
        tm = TrainModel()
        assert tm.trainer_image == ""

    def test_train_model_explicit_image_honored(self):
        """Explicit trainer_image overrides auto-derivation."""
        tm = TrainModel(trainer_image="my-custom-image:latest")
        assert tm.trainer_image == "my-custom-image:latest"

    def test_train_model_resolve_image_uri(self, test_context):
        """TrainModel.resolve_image_uri derives image from pipeline name + context."""
        tm = TrainModel()
        uri = tm.resolve_image_uri("churn_prediction", test_context)
        assert "churn-prediction" in uri
        assert test_context.artifact_registry_host in uri

    def test_train_model_explicit_image_not_overridden(self, test_context):
        """Explicit trainer_image is returned as-is by resolve_image_uri."""
        tm = TrainModel(trainer_image="gcr.io/my-proj/custom:v1")
        uri = tm.resolve_image_uri("churn_prediction", test_context)
        assert uri == "gcr.io/my-proj/custom:v1"


# ═══════════════════════════════════════════════════════════════════════
# 2.2 DAG Local Runner
# ═══════════════════════════════════════════════════════════════════════


class TestDAGLocalRunner:
    def test_dag_runner_topological_order(self, test_context, tmp_path):
        """Tasks execute in valid topological order."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        # Create a DAG with non-linear deps: a → c, b → c
        dag_def = (
            DAGBuilder(name="topo-test", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1 AS x"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2 AS y"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3 AS z"), name="c", depends_on=["a", "b"])
            .build()
        )
        runner = DAGLocalRunner(test_context)
        execution_order = runner.run(dag_def)
        # c should come after both a and b
        names = list(execution_order.keys())
        assert names.index("c") > names.index("a")
        assert names.index("c") > names.index("b")

    def test_dag_runner_bq_query_via_duckdb(self, test_context, tmp_path):
        """BQQueryTask executes SQL against DuckDB with seed data."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        # Create seed data
        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()
        (seeds_dir / "raw_data.csv").write_text("id,value\n1,100\n2,200\n")

        dag_def = (
            DAGBuilder(name="bq-test", schedule="@daily")
            .task(
                BQQueryTask(
                    sql="SELECT id, value * 2 AS doubled FROM \"{bq_dataset}\".\"raw_data\"",
                    destination_table="doubled_data",
                ),
                name="double_it",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context, seeds_dir=seeds_dir)
        outputs = runner.run(dag_def)
        assert "double_it" in outputs

        # Verify the destination table was created in DuckDB
        result = runner._conn.sql(
            f'SELECT * FROM "{test_context.bq_dataset}"."doubled_data" ORDER BY id'
        ).fetchall()
        assert len(result) == 2
        assert result[0][1] == 200  # value * 2
        assert result[1][1] == 400

    def test_dag_runner_email_prints_to_console(self, test_context, capsys):
        """EmailTask prints recipients and subject, does not send."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        dag_def = (
            DAGBuilder(name="email-test", schedule="@daily")
            .task(
                EmailTask(
                    to=["team@co.com"],
                    subject="Test subject {namespace}",
                    body="Test body",
                ),
                name="notify",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context)
        runner.run(dag_def)
        captured = capsys.readouterr()
        assert "team@co.com" in captured.out
        assert "Test subject" in captured.out

    def test_dag_runner_sql_file_loaded(self, test_context, tmp_path):
        """BQQueryTask with sql_file loads and executes the file contents."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        # Create SQL file
        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        (sql_dir / "query.sql").write_text("SELECT 42 AS answer")

        dag_def = (
            DAGBuilder(name="sql-file-test", schedule="@daily")
            .task(
                BQQueryTask(sql_file="sql/query.sql"),
                name="run_sql",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context, pipeline_dir=tmp_path)
        outputs = runner.run(dag_def)
        assert "run_sql" in outputs

    def test_dag_runner_bq_compat_translation(self, test_context, tmp_path):
        """BQQueryTask SQL goes through bq_to_duckdb() translation."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()
        (seeds_dir / "raw_data.csv").write_text("id,value\n1,100\n2,0\n")

        dag_def = (
            DAGBuilder(name="compat-test", schedule="@daily")
            .task(
                BQQueryTask(
                    sql="SELECT id, SAFE_DIVIDE(value, value) AS ratio FROM `{bq_dataset}.raw_data`",
                    destination_table="compat_output",
                ),
                name="compat",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context, seeds_dir=seeds_dir)
        outputs = runner.run(dag_def)
        result = runner._conn.sql(
            f'SELECT * FROM "{test_context.bq_dataset}"."compat_output" ORDER BY id'
        ).fetchall()
        assert result[0][1] == 1.0  # 100/100
        assert result[1][1] is None  # 0/0 → NULL

    def test_dag_runner_resolves_run_date(self, test_context):
        """DAG runner replaces {run_date} in SQL with the actual run date."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        dag_def = (
            DAGBuilder(name="date-test", schedule="@daily")
            .task(
                BQQueryTask(sql="SELECT '{run_date}' AS dt"),
                name="date_check",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context)
        outputs = runner.run(dag_def, run_date="2024-06-15")
        assert "date_check" in outputs

    def test_dag_runner_seed_data_loaded(self, test_context, tmp_path):
        """Seed CSV files are loaded into DuckDB before task execution."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        seeds_dir = tmp_path / "seeds"
        seeds_dir.mkdir()
        (seeds_dir / "test_table.csv").write_text("a,b\n1,2\n3,4\n")

        dag_def = (
            DAGBuilder(name="seed-test", schedule="@daily")
            .task(
                BQQueryTask(
                    sql='SELECT SUM(a) AS total FROM "{bq_dataset}"."test_table"',
                    destination_table="summed",
                ),
                name="sum_it",
            )
            .build()
        )
        runner = DAGLocalRunner(test_context, seeds_dir=seeds_dir)
        runner.run(dag_def)
        result = runner._conn.sql(
            f'SELECT total FROM "{test_context.bq_dataset}"."summed"'
        ).fetchone()
        assert result[0] == 4  # 1 + 3


# ═══════════════════════════════════════════════════════════════════════
# 2.2 cmd_run.py integration — detect dag.py vs pipeline.py
# ═══════════════════════════════════════════════════════════════════════


class TestCmdRunDAGDetection:
    def test_run_local_detects_dag_py(self, tmp_path, test_context):
        """_run_local detects dag.py and uses DAGLocalRunner."""
        # Create a pipeline dir with dag.py
        pipe_dir = tmp_path / "pipelines" / "test_dag"
        pipe_dir.mkdir(parents=True)
        (pipe_dir / "dag.py").write_text(
            "from gcp_ml_framework.dag.builder import DAGBuilder\n"
            "from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask\n"
            "dag = DAGBuilder(name='test', schedule='@daily')"
            ".task(BQQueryTask(sql='SELECT 1'), name='t').build()\n"
        )
        # Should not raise when loading
        from gcp_ml_framework.cli.cmd_compile import _load_dag

        dag_def = _load_dag(pipe_dir)
        assert isinstance(dag_def, DAGDefinition)


# ═══════════════════════════════════════════════════════════════════════
# 2.2 Fix auto_wrap_pipeline_dag in factory.py
# ═══════════════════════════════════════════════════════════════════════


class TestAutoWrapPipelineDAG:
    def test_auto_wrap_pipeline_dag_exists(self):
        """auto_wrap_pipeline_dag must exist in factory.py."""
        from gcp_ml_framework.dag import factory

        assert hasattr(factory, "auto_wrap_pipeline_dag")

    def test_auto_wrap_pipeline_dag_writes_file(self, test_context, tmp_path):
        """auto_wrap_pipeline_dag writes a DAG file and returns the path."""
        from gcp_ml_framework.dag.factory import auto_wrap_pipeline_dag
        from gcp_ml_framework.pipeline.builder import PipelineBuilder
        from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract

        pipeline_def = (
            PipelineBuilder(name="test-pipe", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .build()
        )
        dag_path = auto_wrap_pipeline_dag(pipeline_def, test_context, tmp_path)
        assert dag_path.exists()
        assert dag_path.suffix == ".py"
        content = dag_path.read_text()
        assert "gcp_ml_framework" not in content


# ═══════════════════════════════════════════════════════════════════════
# 2.3 Churn prediction use case updates
# ═══════════════════════════════════════════════════════════════════════


class TestChurnPredictionUpdates:
    def test_churn_pipeline_exists(self):
        """churn_prediction pipeline directory exists."""
        assert Path("pipelines/churn_prediction").is_dir()

    def test_churn_no_explicit_trainer_image(self):
        """TrainModel in churn pipeline should not have explicit trainer_image."""
        from pipelines.churn_prediction.pipeline import pipeline

        train_step = [s for s in pipeline.steps if s.stage == "train"][0]
        # Empty string means auto-derive
        assert train_step.component.trainer_image == ""

    def test_churn_uses_n2_machine_types(self):
        """Churn pipeline must use n2 (not n1) machine types."""
        from pipelines.churn_prediction.pipeline import pipeline

        for step in pipeline.steps:
            if hasattr(step.component, "machine_type"):
                assert "n1" not in step.component.machine_type, (
                    f"{step.name} uses legacy n1: {step.component.machine_type}"
                )

    def test_churn_no_trainer_dockerfile(self):
        """trainer/Dockerfile should NOT exist (platform auto-generates)."""
        assert not Path("pipelines/churn_prediction/trainer/Dockerfile").exists()

    def test_churn_has_requirements_txt(self):
        """trainer/requirements.txt must exist for Docker auto-generation."""
        assert Path("pipelines/churn_prediction/trainer/requirements.txt").exists()

    def test_churn_has_trainer_script(self):
        """trainer/train.py must exist."""
        assert Path("pipelines/churn_prediction/trainer/train.py").exists()


# ═══════════════════════════════════════════════════════════════════════
# 2.4 Sales Analytics use case
# ═══════════════════════════════════════════════════════════════════════


class TestSalesAnalytics:
    def test_sales_analytics_dag_exists(self):
        """sales_analytics/dag.py must exist."""
        assert Path("pipelines/sales_analytics/dag.py").exists()

    def test_sales_analytics_has_8_tasks(self):
        """DAG should have 8 tasks."""
        from pipelines.sales_analytics.dag import dag

        assert len(dag.tasks) == 8

    def test_sales_analytics_dag_shape(self):
        """DAG has correct fan-out / fan-in pattern."""
        from pipelines.sales_analytics.dag import dag

        by_name = {t.name: t for t in dag.tasks}

        # Root tasks (extractions) have no deps
        for name in ["extract_orders", "extract_inventory", "extract_returns"]:
            assert by_name[name].depends_on == [], f"{name} should be a root"

        # Aggregations depend on their respective extractions
        assert "extract_orders" in by_name["agg_revenue"].depends_on
        assert "extract_inventory" in by_name["check_stock"].depends_on
        assert "extract_returns" in by_name["agg_refunds"].depends_on

        # build_report fans in from all 3 aggregations
        build_deps = set(by_name["build_report"].depends_on)
        assert {"agg_revenue", "check_stock", "agg_refunds"} == build_deps

        # notify depends on build_report
        assert "build_report" in by_name["notify"].depends_on

    def test_sales_analytics_uses_sql_files(self):
        """SQL tasks should use sql_file references."""
        from pipelines.sales_analytics.dag import dag

        sql_tasks = [t for t in dag.tasks if isinstance(t.task, BQQueryTask)]
        sql_file_count = sum(1 for t in sql_tasks if t.task.sql_file)
        assert sql_file_count >= 7, "Most BQ tasks should use sql_file"

    def test_sales_analytics_sql_files_exist(self):
        """All referenced SQL files must exist."""
        from pipelines.sales_analytics.dag import dag

        for t in dag.tasks:
            if isinstance(t.task, BQQueryTask) and t.task.sql_file:
                path = Path("pipelines/sales_analytics") / t.task.sql_file
                assert path.exists(), f"SQL file missing: {path}"

    def test_sales_analytics_seed_data_exists(self):
        """Seed CSV files must exist for local testing."""
        seeds = Path("pipelines/sales_analytics/seeds")
        assert seeds.exists()
        assert (seeds / "raw_orders.csv").exists()
        assert (seeds / "raw_inventory.csv").exists()
        assert (seeds / "raw_returns.csv").exists()

    def test_sales_analytics_compiles(self, test_context, tmp_path):
        """DAG compiles to valid Airflow Python file."""
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from pipelines.sales_analytics.dag import dag

        compiler = DAGCompiler(output_dir=tmp_path, pipeline_dir=Path("pipelines/sales_analytics"))
        path = compiler.compile(dag, test_context)
        assert path.exists()
        ast.parse(path.read_text())

    def test_sales_analytics_compiled_no_framework_imports(self, test_context, tmp_path):
        """Compiled DAG has zero gcp_ml_framework imports."""
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from pipelines.sales_analytics.dag import dag

        compiler = DAGCompiler(output_dir=tmp_path, pipeline_dir=Path("pipelines/sales_analytics"))
        path = compiler.compile(dag, test_context)
        content = path.read_text()
        assert "gcp_ml_framework" not in content

    def test_sales_analytics_local_run(self, test_context):
        """Local run executes all 8 tasks against seed data."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner
        from pipelines.sales_analytics.dag import dag

        seeds_dir = Path("pipelines/sales_analytics/seeds")
        pipeline_dir = Path("pipelines/sales_analytics")
        runner = DAGLocalRunner(
            test_context, seeds_dir=seeds_dir, pipeline_dir=pipeline_dir
        )
        outputs = runner.run(dag, run_date="2026-03-01")
        assert len(outputs) == 8


# ═══════════════════════════════════════════════════════════════════════
# 2.5 Recommendation Engine use case
# ═══════════════════════════════════════════════════════════════════════


class TestRecommendationEngine:
    def test_reco_dag_exists(self):
        """recommendation_engine/dag.py must exist."""
        assert Path("pipelines/recommendation_engine/dag.py").exists()

    def test_reco_has_vertex_pipeline_tasks(self):
        """DAG should have at least 2 VertexPipelineTasks."""
        from pipelines.recommendation_engine.dag import dag

        vp_tasks = [t for t in dag.tasks if isinstance(t.task, VertexPipelineTask)]
        assert len(vp_tasks) >= 2

    def test_reco_has_bq_tasks(self):
        """DAG should have BQQueryTasks for feature extraction."""
        from pipelines.recommendation_engine.dag import dag

        bq_tasks = [t for t in dag.tasks if isinstance(t.task, BQQueryTask)]
        assert len(bq_tasks) >= 1

    def test_reco_has_email_task(self):
        """DAG should have an EmailTask for notification."""
        from pipelines.recommendation_engine.dag import dag

        email_tasks = [t for t in dag.tasks if isinstance(t.task, EmailTask)]
        assert len(email_tasks) >= 1

    def test_reco_compiles(self, test_context, tmp_path):
        """DAG compiles to valid Airflow Python file."""
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from pipelines.recommendation_engine.dag import dag

        compiler = DAGCompiler(output_dir=tmp_path, pipeline_dir=Path("pipelines/recommendation_engine"))
        path = compiler.compile(dag, test_context)
        assert path.exists()
        ast.parse(path.read_text())

    def test_reco_compiled_no_framework_imports(self, test_context, tmp_path):
        """Compiled DAG has zero gcp_ml_framework imports."""
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from pipelines.recommendation_engine.dag import dag

        compiler = DAGCompiler(output_dir=tmp_path, pipeline_dir=Path("pipelines/recommendation_engine"))
        path = compiler.compile(dag, test_context)
        content = path.read_text()
        assert "gcp_ml_framework" not in content

    def test_reco_has_trainer(self):
        """trainer/train.py and requirements.txt must exist."""
        assert Path("pipelines/recommendation_engine/trainer/train.py").exists()
        assert Path("pipelines/recommendation_engine/trainer/requirements.txt").exists()

    def test_reco_no_trainer_dockerfile(self):
        """trainer/Dockerfile should NOT exist (platform auto-generates)."""
        assert not Path("pipelines/recommendation_engine/trainer/Dockerfile").exists()

    def test_reco_seed_data_exists(self):
        """Seed CSV must exist for local testing."""
        seeds = Path("pipelines/recommendation_engine/seeds")
        assert (seeds / "raw_interactions.csv").exists()

    def test_reco_sql_files_exist(self):
        """SQL files must exist."""
        sql_dir = Path("pipelines/recommendation_engine/sql")
        assert sql_dir.exists()
        assert (sql_dir / "extract_interactions.sql").exists()

    def test_reco_vertex_pipeline_definitions_exist(self):
        """Pipeline definitions referenced by VertexPipelineTasks must exist."""
        from pipelines.recommendation_engine.dag import dag

        for t in dag.tasks:
            if isinstance(t.task, VertexPipelineTask):
                # Check that the pipeline .py file exists
                vp_name = t.task.pipeline_name
                pipe_dir = Path("pipelines") / vp_name
                assert (pipe_dir / "pipeline.py").exists(), (
                    f"Pipeline {vp_name}/pipeline.py missing for VertexPipelineTask"
                )

    def test_reco_local_run(self, test_context):
        """Local run executes DAG including Vertex pipeline stubs."""
        from gcp_ml_framework.dag.runner import DAGLocalRunner
        from pipelines.recommendation_engine.dag import dag

        seeds_dir = Path("pipelines/recommendation_engine/seeds")
        pipeline_dir = Path("pipelines/recommendation_engine")
        runner = DAGLocalRunner(
            test_context, seeds_dir=seeds_dir, pipeline_dir=pipeline_dir
        )
        outputs = runner.run(dag, run_date="2026-03-01")
        assert len(outputs) >= 4  # at least BQ + 2 Vertex + email
