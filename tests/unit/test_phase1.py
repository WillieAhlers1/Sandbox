"""Phase 1 tests — Clean Foundation.

TDD: These tests are written BEFORE the implementation.
They define the expected behavior for all Phase 1 changes.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.config import FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.naming import NamingConvention


# ── 1.1a: as_airflow_operator removed from BaseComponent ──────────────────────


class TestRemoveAsAirflowOperator:
    def test_base_component_has_no_as_airflow_operator(self):
        """BaseComponent should NOT have as_airflow_operator method."""
        from gcp_ml_framework.components.base import BaseComponent

        assert not hasattr(BaseComponent, "as_airflow_operator")

    def test_base_component_docstring_no_airflow_reference(self):
        """Module docstring should not reference as_airflow_operator."""
        import gcp_ml_framework.components.base as mod

        assert "as_airflow_operator" not in (mod.__doc__ or "")


# ── 1.1b: PandasTransform removed ────────────────────────────────────────────


class TestRemovePandasTransform:
    def test_no_pandas_transform_in_bq_transform_module(self):
        """PandasTransform should not exist in bq_transform module."""
        from gcp_ml_framework.components.transformation import bq_transform

        assert not hasattr(bq_transform, "PandasTransform")

    def test_bq_transform_still_exists(self):
        """BQTransform should still be importable."""
        from gcp_ml_framework.components.transformation.bq_transform import BQTransform

        assert BQTransform is not None


# ── 1.1c: Fabricated Composer methods removed from naming ─────────────────────


class TestRemoveComposerMethods:
    def test_naming_has_no_composer_environment_name(self, naming_dev):
        """Verify fabricated composer_environment_name is removed."""
        assert not hasattr(naming_dev, "composer_environment_name")

    def test_naming_has_no_gcs_dag_sync_path(self, naming_dev):
        """Verify fabricated gcs_dag_sync_path is removed."""
        assert not hasattr(naming_dev, "gcs_dag_sync_path")


# ── 1.1d: Machine types updated to n2 ────────────────────────────────────────


class TestMachineTypeDefaults:
    def test_component_config_default_n2(self):
        """ComponentConfig default machine_type should be n2-standard-4."""
        from gcp_ml_framework.components.base import ComponentConfig

        cfg = ComponentConfig()
        assert cfg.machine_type == "n2-standard-4"

    def test_train_model_default_n2(self):
        """TrainModel default machine_type should be n2-standard-4."""
        from gcp_ml_framework.components.ml.train import TrainModel

        tm = TrainModel(trainer_image="test")
        assert tm.machine_type == "n2-standard-4"

    def test_deploy_model_default_n2(self):
        """DeployModel default machine_type should be n2-standard-2."""
        from gcp_ml_framework.components.ml.deploy import DeployModel

        dm = DeployModel(endpoint_name="test")
        assert dm.machine_type == "n2-standard-2"


# ── 1.2a: EvaluateModel.local_run deterministic ──────────────────────────────


class TestEvaluateModelDeterministic:
    def test_evaluate_local_run_no_random(self, test_context):
        """local_run must return deterministic results — not random."""
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel

        eval_comp = EvaluateModel(metrics=["auc", "f1"], gate={})
        result1 = eval_comp.local_run(test_context)
        result2 = eval_comp.local_run(test_context)
        assert result1 == result2

    def test_evaluate_local_run_returns_placeholder_values(self, test_context):
        """local_run returns fixed placeholder values when no model available."""
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel

        eval_comp = EvaluateModel(metrics=["auc", "f1"], gate={})
        result = eval_comp.local_run(test_context)
        assert "auc" in result
        assert "f1" in result
        # Should be fixed placeholders, not high values suggesting real computation
        assert isinstance(result["auc"], float)
        assert isinstance(result["f1"], float)

    def test_evaluate_no_random_import(self):
        """evaluate.py should not import random."""
        import inspect

        from gcp_ml_framework.components.ml import evaluate

        source = inspect.getsource(evaluate)
        assert "import random" not in source


# ── 1.2b: utils/bq.py exception handling ─────────────────────────────────────


class TestBqTableExists:
    def test_table_exists_returns_true_when_found(self):
        """table_exists returns True when table is found."""
        from gcp_ml_framework.utils.bq import table_exists

        mock_client = MagicMock()
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            result = table_exists("proj", "ds", "tbl")
        assert result is True

    def test_table_exists_returns_false_on_not_found(self):
        """table_exists returns False only when table is NotFound."""
        from google.api_core.exceptions import NotFound

        from gcp_ml_framework.utils.bq import table_exists

        mock_client = MagicMock()
        mock_client.get_table.side_effect = NotFound("not found")
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            result = table_exists("proj", "ds", "tbl")
        assert result is False

    def test_table_exists_raises_on_permission_denied(self):
        """table_exists should NOT swallow PermissionDenied."""
        from google.api_core.exceptions import Forbidden

        from gcp_ml_framework.utils.bq import table_exists

        mock_client = MagicMock()
        mock_client.get_table.side_effect = Forbidden("denied")
        with patch("google.cloud.bigquery.Client", return_value=mock_client):
            with pytest.raises(Forbidden):
                table_exists("proj", "ds", "tbl")


# ── 1.2c: composer_dags_path in config ────────────────────────────────────────


class TestComposerDagsPath:
    def test_gcp_config_has_composer_dags_path(self):
        """GCPConfig should have composer_dags_path dict, not composer_env."""
        cfg = GCPConfig()
        assert hasattr(cfg, "composer_dags_path")
        assert isinstance(cfg.composer_dags_path, dict)

    def test_gcp_config_no_composer_env(self):
        """GCPConfig should NOT have composer_env anymore."""
        cfg = GCPConfig()
        assert not hasattr(cfg, "composer_env")

    def test_composer_dags_path_per_environment(self):
        """composer_dags_path can be set per environment."""
        cfg = GCPConfig(
            dev_project_id="dev",
            composer_dags_path={
                "dev": "gs://dev-composer-bucket/dags",
                "staging": "gs://staging-composer-bucket/dags",
                "prod": "gs://prod-composer-bucket/dags",
            },
        )
        assert cfg.composer_dags_path["dev"] == "gs://dev-composer-bucket/dags"

    def test_context_no_composer_env(self):
        """MLContext should use composer_dags_path, not composer_env."""
        cfg = FrameworkConfig(
            team="t",
            project="p",
            branch="feature/test",
            gcp=GCPConfig(
                dev_project_id="dev",
                staging_project_id="staging",
                prod_project_id="prod",
                composer_dags_path={"dev": "gs://bucket/dags"},
            ),
        )
        ctx = MLContext.from_config(cfg)
        assert hasattr(ctx, "composer_dags_path")
        assert not hasattr(ctx, "composer_env")


# ── 1.3a: gml compile command ────────────────────────────────────────────────


class TestCompileCommand:
    def test_compile_module_exists(self):
        """cmd_compile.py module should exist and be importable."""
        from gcp_ml_framework.cli import cmd_compile

        assert hasattr(cmd_compile, "compile_cmd")

    def test_compile_registered_in_app(self):
        """compile should be registered as a command in the main app."""
        from typer.testing import CliRunner

        from gcp_ml_framework.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["compile", "--help"])
        assert result.exit_code == 0
        assert "compile" in result.output.lower() or "usage" in result.output.lower()


# ── 1.3b: gml deploy unified ─────────────────────────────────────────────────


class TestDeployUnified:
    def test_deploy_is_single_command(self):
        """deploy should be a single command, not a sub-app with subcommands."""
        from typer.testing import CliRunner

        from gcp_ml_framework.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["deploy", "--help"])
        assert result.exit_code == 0
        # Should NOT show "dags" or "features" as subcommands
        assert "dags" not in result.output.lower() or "Commands" not in result.output


# ── 1.3c: gml promote removed ────────────────────────────────────────────────


class TestPromoteRemoved:
    def test_no_promote_command(self):
        """promote should NOT exist as a command."""
        from typer.testing import CliRunner

        from gcp_ml_framework.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert "promote" not in result.output

    def test_no_cmd_promote_module(self):
        """cmd_promote.py should not exist."""
        import importlib

        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module("gcp_ml_framework.cli.cmd_promote")


# ── 1.3d: gml run has no --compile-only ───────────────────────────────────────


class TestRunNoCompileOnly:
    def test_run_no_compile_only_flag(self):
        """gml run should NOT have --compile-only flag."""
        from typer.testing import CliRunner

        from gcp_ml_framework.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["run", "--help"])
        assert "--compile-only" not in result.output


# ── 1.4a: BQQueryTask sql_file support ────────────────────────────────────────


class TestBQQueryTaskSqlFile:
    def test_sql_file_field_exists(self):
        """BQQueryTask should have a sql_file field."""
        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        t = BQQueryTask(sql_file="sql/query.sql")
        assert t.sql_file == "sql/query.sql"

    def test_sql_and_sql_file_mutually_exclusive(self, test_context):
        """Cannot specify both sql and sql_file."""
        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        t = BQQueryTask(sql="SELECT 1", sql_file="sql/query.sql")
        errors = t.validate(test_context)
        assert any("mutually exclusive" in e.lower() or "both" in e.lower() for e in errors)

    def test_sql_file_loads_content(self, tmp_path, test_context):
        """sql_file loads SQL content from the file."""
        sql_content = "SELECT * FROM `{bq_dataset}.orders` WHERE dt = '{run_date}'"
        sql_file = tmp_path / "query.sql"
        sql_file.write_text(sql_content)

        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        t = BQQueryTask(sql_file=str(sql_file))
        resolved = t.resolve_sql(test_context, pipeline_dir=tmp_path)
        assert test_context.bq_dataset in resolved
        assert "{{ ds }}" in resolved

    def test_sql_file_template_resolution(self, tmp_path, test_context):
        """Template macros in loaded SQL are resolved."""
        sql_file = tmp_path / "query.sql"
        sql_file.write_text("SELECT * FROM `{bq_dataset}.t` WHERE ns = '{namespace}'")

        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        t = BQQueryTask(sql_file=str(sql_file))
        resolved = t.resolve_sql(test_context, pipeline_dir=tmp_path)
        assert test_context.bq_dataset in resolved
        assert test_context.namespace in resolved

    def test_validate_empty_sql_no_file(self, test_context):
        """Validation fails when neither sql nor sql_file is provided."""
        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        t = BQQueryTask()
        errors = t.validate(test_context)
        assert len(errors) > 0


# ── 1.4b: VertexPipelineTask + self-contained DAG compiler ───────────────────


class TestSelfContainedDags:
    def test_vertex_pipeline_renders_no_framework_imports(self, test_context):
        """Generated DAG code must NOT import from gcp_ml_framework."""
        from gcp_ml_framework.dag.builder import DAGBuilder
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        dag_def = (
            DAGBuilder(name="test_ml", schedule="@daily")
            .task(VertexPipelineTask(pipeline_name="churn_prediction"), name="run_ml")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "gcp_ml_framework" not in source

    def test_vertex_pipeline_uses_run_pipeline_job_operator(self, test_context):
        """Generated code must use RunPipelineJobOperator."""
        from gcp_ml_framework.dag.builder import DAGBuilder
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        dag_def = (
            DAGBuilder(name="test_ml", schedule="@daily")
            .task(VertexPipelineTask(pipeline_name="churn_prediction"), name="run_ml")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "RunPipelineJobOperator" in source

    def test_vertex_pipeline_references_gcs_yaml(self, test_context):
        """Generated code must reference the compiled YAML at its GCS path."""
        from gcp_ml_framework.dag.builder import DAGBuilder
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        dag_def = (
            DAGBuilder(name="test_ml", schedule="@daily")
            .task(VertexPipelineTask(pipeline_name="churn_prediction"), name="run_ml")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "template_path" in source
        assert "churn_prediction" in source
        assert "pipeline.yaml" in source

    def test_vertex_pipeline_rendered_is_valid_python(self, test_context):
        """Generated DAG with VertexPipelineTask is valid Python."""
        from gcp_ml_framework.dag.builder import DAGBuilder
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        dag_def = (
            DAGBuilder(name="test_ml", schedule="@daily")
            .task(VertexPipelineTask(pipeline_name="churn_prediction"), name="run_ml")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        ast.parse(source)  # Must not raise SyntaxError


# ── 1.4c: DAG compiler header ────────────────────────────────────────────────


class TestDagCompilerHeader:
    def test_header_says_gml_compile(self, test_context):
        """Generated DAG header should say 'gml compile', not 'gml deploy dags'."""
        from gcp_ml_framework.dag.builder import DAGBuilder
        from gcp_ml_framework.dag.compiler import DAGCompiler
        from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask

        dag_def = (
            DAGBuilder(name="test", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="t")
            .build()
        )
        compiler = DAGCompiler()
        source = compiler.render(dag_def, test_context)
        assert "gml compile" in source
        assert "gml deploy dags" not in source
