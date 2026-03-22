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
# @task → @ml_task data bridging (5.15)
# ---------------------------------------------------------------------------


class TestDataBridging:
    """SmartCompiler bridges data between @task and @ml_task groups."""

    def test_compute_task_output_bq_query(self, mock_context):
        """BQQuery with destination_table produces deterministic output ref."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        step = PipelineStep(
            name="ingest",
            component=BQQuery(sql="SELECT 1", destination_table="raw_data"),
            task_type=TaskType.TASK,
        )
        compiler = SmartCompiler()
        output = compiler._compute_task_output(step, mock_context)
        assert output == (
            f"{mock_context.gcp_project}.{mock_context.bq_dataset}.raw_data"
        )

    def test_compute_task_output_bq_transform(self, mock_context):
        """BQTransform with output_table produces deterministic output ref."""
        from gcp_ml_framework.components.transformation.bq_transform import (
            BQTransform,
        )

        step = PipelineStep(
            name="transform",
            component=BQTransform(
                sql="SELECT 1", output_table="features"
            ),
            task_type=TaskType.TASK,
        )
        compiler = SmartCompiler()
        output = compiler._compute_task_output(step, mock_context)
        assert output == (
            f"{mock_context.gcp_project}.{mock_context.bq_dataset}.features"
        )

    def test_compute_task_output_none_for_no_output(self, mock_context):
        """Component without destination_table/output_table returns None."""
        step = PipelineStep(
            name="noop",
            component=DummyTask(component_name="noop"),
            task_type=TaskType.TASK,
        )
        compiler = SmartCompiler()
        output = compiler._compute_task_output(step, mock_context)
        assert output is None

    def test_bridged_params_in_dag(self, mock_context, tmp_path):
        """BQTransform output flows as parameter_values to RunPipelineJobOperator."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery
        from gcp_ml_framework.components.transformation.bq_transform import (
            BQTransform,
        )

        defn = (
            Pipeline(name="bridging_test", schedule="@daily")
            .add(
                BQQuery(sql="SELECT 1", destination_table="raw"),
                name="ingest",
            )
            .add(
                BQTransform(sql="SELECT 1", output_table="features"),
                name="transform",
            )
            .add(DummyML(), name="train")
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
        # The RunPipelineJobOperator should include dataset_uri
        assert "dataset_uri" in source
        expected_table = (
            f"{mock_context.gcp_project}.{mock_context.bq_dataset}.features"
        )
        assert expected_table in source

    def test_no_bridge_without_task_output(self, mock_context, tmp_path):
        """Pure @ml_task pipeline has no bridged dataset_uri in parameter_values."""
        defn = (
            Pipeline(name="no_bridge", schedule="@daily")
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
        assert "dataset_uri" not in source


# ---------------------------------------------------------------------------
# Mixed execution scenario (5.16)
# ---------------------------------------------------------------------------


class TestMixedExecutionScenario:
    """Verify @task→@ml_task→@task→@ml_task produces correct groups and DAG."""

    def _build_mixed_pipeline(self):
        """Build a 4-step mixed pipeline: @task → @ml_task → @task → @ml_task."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery
        from gcp_ml_framework.components.transformation.bq_transform import (
            BQTransform,
        )

        return (
            Pipeline(name="mixed_test", schedule=None)
            .add(
                BQQuery(
                    sql="SELECT 1",
                    destination_table="mixed_raw",
                    component_name="ingest",
                ),
                name="Ingest",
            )
            .add(DummyML(), name="Train First")
            .add(
                BQTransform(
                    sql="SELECT 1",
                    output_table="mixed_scored",
                    component_name="post_process",
                ),
                name="Post Process",
            )
            .add(DummyML(), name="Register")
            .build()
        )

    def test_mixed_pipeline_four_groups(self):
        """@task→@ml_task→@task→@ml_task produces 4 groups."""
        defn = self._build_mixed_pipeline()
        compiler = SmartCompiler()
        groups = compiler._group_steps(defn.steps)
        assert len(groups) == 4
        assert [g.task_type for g in groups] == [
            TaskType.TASK,
            TaskType.ML_TASK,
            TaskType.TASK,
            TaskType.ML_TASK,
        ]

    def test_mixed_pipeline_step_types(self):
        """Pipeline steps have correct alternating task types."""
        defn = self._build_mixed_pipeline()
        types = [s.task_type for s in defn.steps]
        assert types == [
            TaskType.TASK,
            TaskType.ML_TASK,
            TaskType.TASK,
            TaskType.ML_TASK,
        ]

    def test_mixed_pipeline_compiles(self, mock_context, tmp_path):
        """SmartCompiler produces 2 KFP YAMLs + DAG with 4 tasks."""
        defn = self._build_mixed_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        assert len(result.yaml_paths) == 2
        assert result.dag_path.exists()
        source = result.dag_path.read_text()
        # Two RunPipelineJobOperator tasks
        assert "run_vertex_pipeline_1" in source
        assert "run_vertex_pipeline_3" in source
        # Two BQ operator tasks
        assert "ingest" in source
        assert "post_process" in source
        # Dependencies chain all 4
        assert ">>" in source
        # Bridged dataset_uri in first ML group
        assert "dataset_uri" in source

    def test_mixed_dag_is_valid_python(self, mock_context, tmp_path):
        """Mixed DAG is syntactically valid Python."""
        defn = self._build_mixed_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        compile(source, "<test_mixed_dag>", "exec")


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
