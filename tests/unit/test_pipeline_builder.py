"""Unit tests for pipeline/builder.py — PipelineBuilder DSL."""

import pytest

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.pipeline.builder import PipelineBuilder, PipelineDefinition


@pytest.fixture
def simple_pipeline() -> PipelineDefinition:
    return (
        PipelineBuilder(name="test-pipeline", schedule="@daily")
        .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
        .transform(BQTransform(sql="SELECT * FROM raw", output_table="features"))
        .build()
    )


@pytest.fixture
def full_pipeline() -> PipelineDefinition:
    return (
        PipelineBuilder(name="full-pipeline", schedule="0 6 * * 1")
        .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
        .transform(BQTransform(sql="SELECT * FROM raw", output_table="features"))
        .write_features(WriteFeatures(entity="user", feature_group="behavioral"))
        .train(TrainModel(trainer_image="my-image:latest"))
        .evaluate(EvaluateModel(gate={"auc": 0.75}))
        .deploy(DeployModel(endpoint_name="my-endpoint"))
        .build()
    )


class TestPipelineBuilder:
    def test_returns_pipeline_definition(self, simple_pipeline):
        assert isinstance(simple_pipeline, PipelineDefinition)

    def test_name_preserved(self, simple_pipeline):
        assert simple_pipeline.name == "test-pipeline"

    def test_schedule_preserved(self, simple_pipeline):
        assert simple_pipeline.schedule == "@daily"

    def test_step_count(self, simple_pipeline):
        assert len(simple_pipeline.steps) == 2

    def test_full_pipeline_step_count(self, full_pipeline):
        assert len(full_pipeline.steps) == 6

    def test_step_names_unique(self, full_pipeline):
        names = full_pipeline.step_names
        assert len(names) == len(set(names))

    def test_stage_labels(self, full_pipeline):
        stages = [s.stage for s in full_pipeline.steps]
        assert "ingest" in stages
        assert "transform" in stages
        assert "train" in stages
        assert "evaluate" in stages
        assert "deploy" in stages

    def test_empty_pipeline_raises(self):
        with pytest.raises(ValueError, match="no steps"):
            PipelineBuilder(name="empty").build()

    def test_schedule_none(self):
        pipeline = (
            PipelineBuilder(name="manual", schedule=None)
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .build()
        )
        assert pipeline.schedule is None

    def test_custom_step_name(self):
        pipeline = (
            PipelineBuilder(name="named", schedule="@once")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"), name="my_ingest")
            .build()
        )
        assert pipeline.steps[0].name == "my_ingest"

    def test_feature_engineering_only(self):
        """Pipeline without train/deploy should work fine."""
        pipeline = (
            PipelineBuilder(name="feature-only", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .transform(BQTransform(sql="SELECT * FROM raw", output_table="features"))
            .write_features(WriteFeatures(entity="user", feature_group="behavioral"))
            .build()
        )
        assert len(pipeline.steps) == 3


class TestLocalRunner:
    def test_print_plan(self, simple_pipeline, test_context, capsys):
        from gcp_ml_framework.pipeline.runner import LocalRunner

        runner = LocalRunner(test_context)
        runner.print_plan(simple_pipeline)
        captured = capsys.readouterr()
        assert "test-pipeline" in captured.out
        assert "ingest" in captured.out

    def test_dry_run(self, simple_pipeline, test_context, capsys):
        from gcp_ml_framework.pipeline.runner import LocalRunner

        runner = LocalRunner(test_context)
        outputs = runner.run(simple_pipeline, dry_run=True)
        assert outputs == {}
