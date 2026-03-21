"""Unit tests for SmartCompiler (gcp_ml_framework.pipeline.smart_compiler)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.config import Environment
from gcp_ml_framework.decorators import TaskType, task
from gcp_ml_framework.pipeline.builder import Pipeline, PipelineStep
from gcp_ml_framework.pipeline.smart_compiler import CompilationResult, SmartCompiler, _StepGroup

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyML(BaseComponent):
    component_name: str = "dummy_ml"


@task
class DummyTask(BaseComponent):
    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# _group_steps
# ---------------------------------------------------------------------------


class TestGroupSteps:
    def test_single_type_one_group(self):
        steps = [
            PipelineStep(
                name="a", component=DummyML(),
                task_type=TaskType.ML_TASK,
            ),
            PipelineStep(
                name="b", component=DummyML(),
                task_type=TaskType.ML_TASK,
            ),
        ]
        compiler = SmartCompiler()
        groups = compiler._group_steps(steps)
        assert len(groups) == 1
        assert groups[0].task_type == TaskType.ML_TASK
        assert len(groups[0].steps) == 2

    def test_mixed_types_split(self):
        steps = [
            PipelineStep(
                name="a",
                component=DummyTask(component_name="a"),
                task_type=TaskType.TASK,
            ),
            PipelineStep(
                name="b", component=DummyML(),
                task_type=TaskType.ML_TASK,
            ),
            PipelineStep(
                name="c",
                component=DummyTask(component_name="c"),
                task_type=TaskType.TASK,
            ),
        ]
        compiler = SmartCompiler()
        groups = compiler._group_steps(steps)
        assert len(groups) == 3
        assert groups[0].task_type == TaskType.TASK
        assert groups[1].task_type == TaskType.ML_TASK
        assert groups[2].task_type == TaskType.TASK

    def test_group_indices(self):
        steps = [
            PipelineStep(
                name="a", component=DummyML(),
                task_type=TaskType.ML_TASK,
            ),
            PipelineStep(
                name="b",
                component=DummyTask(component_name="b"),
                task_type=TaskType.TASK,
            ),
        ]
        compiler = SmartCompiler()
        groups = compiler._group_steps(steps)
        assert groups[0].index == 0
        assert groups[1].index == 1


# ---------------------------------------------------------------------------
# CompilationResult
# ---------------------------------------------------------------------------


class TestCompilationResult:
    def test_defaults(self, tmp_path):
        result = CompilationResult(dag_path=tmp_path / "dag.py")
        assert result.yaml_paths == []

    def test_with_yamls(self, tmp_path):
        result = CompilationResult(
            dag_path=tmp_path / "dag.py",
            yaml_paths=[tmp_path / "a.yaml", tmp_path / "b.yaml"],
        )
        assert len(result.yaml_paths) == 2


# ---------------------------------------------------------------------------
# Pure @task compilation (no KFP needed)
# ---------------------------------------------------------------------------


class TestPureTaskCompile:
    def test_pure_task_no_yaml(self, mock_context, tmp_path):
        """Pure @task pipeline produces a DAG file but no YAML."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        defn = (
            Pipeline(name="etl_only", schedule="@daily")
            .add(BQQuery(sql="SELECT 1"), name="extract")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        result = compiler.compile(defn, mock_context)
        assert result.yaml_paths == []
        assert result.dag_path.exists()

    def test_pure_task_dag_content(self, mock_context, tmp_path):
        """DAG file for pure @task pipeline contains Airflow operators."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        defn = (
            Pipeline(name="etl_only", schedule="@daily")
            .add(BQQuery(sql="SELECT 1"), name="extract")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        result = compiler.compile(defn, mock_context)
        content = result.dag_path.read_text()
        assert "BigQueryInsertJobOperator" in content
        assert "RunPipelineJobOperator" not in content
        assert "DO NOT EDIT MANUALLY" in content


# ---------------------------------------------------------------------------
# Pure @ml_task compilation
# ---------------------------------------------------------------------------


class TestPureMLTaskCompile:
    def test_pure_ml_task_produces_yaml(self, mock_context, tmp_path):
        """Pure @ml_task pipeline produces YAML + DAG."""
        defn = (
            Pipeline(name="ml_only", schedule="@daily")
            .add(DummyML(), name="step_a")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        # PipelineCompiler requires kfp; skip if not installed
        try:
            result = compiler.compile(defn, mock_context)
            assert len(result.yaml_paths) == 1
            assert result.dag_path.exists()
        except ImportError:
            pytest.skip("kfp not installed")

    def test_ml_task_dag_has_valid_jinja(self, mock_context, tmp_path):
        """Generated DAG uses {{ ds }} (double braces), not {{{ ds }}} (triple)."""
        defn = (
            Pipeline(name="jinja_check", schedule="@daily")
            .add(DummyML(), name="step_a")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        # Must have valid Jinja2 double-brace macros, not triple
        assert "{{ ds }}" in source
        assert "{{{ ds }}}" not in source
        assert "{{ ds_nodash }}" in source
        assert "{{{ ds_nodash }}}" not in source


# ---------------------------------------------------------------------------
# _StepGroup dataclass
# ---------------------------------------------------------------------------


class TestStepGroup:
    def test_step_group_creation(self):
        group = _StepGroup(
            task_type=TaskType.TASK,
            steps=[
                PipelineStep(
                    name="a",
                    component=DummyTask(component_name="a"),
                    task_type=TaskType.TASK,
                ),
            ],
            index=0,
        )
        assert group.task_type == TaskType.TASK
        assert len(group.steps) == 1
        assert group.index == 0


# ---------------------------------------------------------------------------
# Generated DAG validity (replaces old DAGCompiler tests)
# ---------------------------------------------------------------------------


class TestGeneratedDag:
    def test_generated_dag_is_valid_python(self, mock_context, tmp_path):
        """SmartCompiler output is syntactically valid Python."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        defn = (
            Pipeline(name="validity_check", schedule="@daily")
            .add(BQQuery(sql="SELECT 1"), name="extract")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        result = compiler.compile(defn, mock_context)
        source = result.dag_path.read_text()
        # compile() raises SyntaxError if the code is invalid
        compile(source, "<test_dag>", "exec")

    def test_dev_schedule_is_none(self, mock_context, tmp_path):
        """DEV environment produces schedule=None in generated DAG."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        assert mock_context.environment == Environment.DEV

        defn = (
            Pipeline(name="dev_sched", schedule="@daily")
            .add(BQQuery(sql="SELECT 1"), name="extract")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        result = compiler.compile(defn, mock_context)
        source = result.dag_path.read_text()
        assert "schedule=None" in source

    def test_non_dev_schedule_preserved(self, tmp_path):
        """Non-DEV environment uses the declared schedule."""
        import os
        from unittest.mock import patch

        from gcp_ml_framework.components.operators.bq_query import BQQuery
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig
        from gcp_ml_framework.context import MLContext

        gcp_cfg = GCPConfig(
            staging_project_id="staging-project",
            region="us-central1",
        )
        with patch.dict(
            os.environ, {"GML_ENVIRONMENT": "staging"}, clear=False
        ):
            cfg = FrameworkConfig(
                team="testteam",
                project="testproject",
                branch="test-branch",
                environment="staging",
                gcp=gcp_cfg,
            )
        ctx = MLContext.from_config(cfg)

        defn = (
            Pipeline(name="staging_sched", schedule="@daily")
            .add(BQQuery(sql="SELECT 1"), name="extract")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        result = compiler.compile(defn, ctx)
        source = result.dag_path.read_text()
        assert "schedule=None" not in source
        assert "@daily" in source


# ---------------------------------------------------------------------------
# @task without render_operator()
# ---------------------------------------------------------------------------


class TestTaskWithoutRenderOperator:
    def test_task_without_render_operator_raises(self, mock_context, tmp_path):
        """@task component without render_operator() raises NotImplementedError."""

        @task
        class NoRenderTask(BaseComponent):
            component_name: str = "no_render"

        defn = (
            Pipeline(name="fail_test", schedule="@daily")
            .add(NoRenderTask(component_name="no_render"), name="bad_step")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        with pytest.raises(NotImplementedError, match="render_operator"):
            compiler.compile(defn, mock_context)
