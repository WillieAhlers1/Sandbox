"""Unit tests for verification_pipeline compilation."""

from __future__ import annotations

import pytest

from gcp_ml_framework.decorators import TaskType
from gcp_ml_framework.pipeline.smart_compiler import SmartCompiler

pytestmark = pytest.mark.unit


class TestVerificationPipelineDefinition:
    """Verify the pipeline definition is correct."""

    def test_step_count(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        # 4 sequential steps; register+deploy are in the condition block
        assert len(pipeline.steps) == 4

    def test_step_names(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        assert pipeline.step_names == [
            "Ingest Raw Data",
            "Transform Features",
            "Train Model",
            "Evaluate Model",
        ]

    def test_mixed_types(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        assert pipeline.has_mixed_types is True

    def test_task_types(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        types = [s.task_type for s in pipeline.steps]
        assert types == [
            TaskType.TASK,
            TaskType.TASK,
            TaskType.ML_TASK,
            TaskType.ML_TASK,
        ]

    def test_has_control_flow(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        assert pipeline.has_control_flow is True
        assert len(pipeline.loop_blocks) == 1
        assert len(pipeline.condition_blocks) == 1

    def test_loop_block_items(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        loop = pipeline.loop_blocks[0]
        assert loop.items == ["us-market", "eu-market"]
        assert loop.item_param == "job_name"

    def test_condition_block_source(self):
        from pipelines.verification_pipeline.pipeline import pipeline

        cond = pipeline.condition_blocks[0]
        assert cond.source_step == "Evaluate Model"
        assert cond.operator == "!="
        assert len(cond.then_steps) == 2


class TestEvaluateVerifyStep:
    """Verify verification pipeline evaluation step."""

    def test_instantiation(self):
        from pipelines.verification_pipeline.steps.evaluate_verify_model import (
            EvaluateVerifyStep,
        )

        step = EvaluateVerifyStep()
        assert step.component_name == "evaluate_verify_model"

    def test_is_evaluate_model_subclass(self):
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel
        from pipelines.verification_pipeline.steps.evaluate_verify_model import (
            EvaluateVerifyStep,
        )

        assert issubclass(EvaluateVerifyStep, EvaluateModel)


class TestVerificationPipelineCompile:
    """Verify SmartCompiler produces correct output."""

    def test_compiles_without_error(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
            assert result.dag_path.exists()
        except ImportError:
            pytest.skip("kfp not installed")

    def test_produces_yaml(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
            assert len(result.yaml_paths) >= 1
        except ImportError:
            pytest.skip("kfp not installed")

    def test_dag_has_bq_operators(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        assert source.count("BigQueryInsertJobOperator") >= 2

    def test_dag_has_vertex_operator(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        assert "RunPipelineJobOperator" in source

    def test_dag_has_dependencies(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        assert ">>" in source

    def test_dag_is_valid_python(self, mock_context, tmp_path):
        from pipelines.verification_pipeline.pipeline import pipeline

        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(pipeline, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        source = result.dag_path.read_text()
        compile(source, "<test_dag>", "exec")
