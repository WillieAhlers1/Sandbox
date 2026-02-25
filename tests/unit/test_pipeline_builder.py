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

    def test_write_features_with_feature_ids(self):
        """WriteFeatures should accept explicit feature_ids list."""
        ids = ["session_count_7d", "days_since_last_login"]
        wf = WriteFeatures(entity="user", feature_group="behavioral", feature_ids=ids)
        assert wf.feature_ids == ids

    def test_write_features_default_feature_ids(self):
        """WriteFeatures feature_ids defaults to empty list."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        assert wf.feature_ids == []

    def test_train_model_kfp_accepts_experiment_name(self):
        """TrainModel KFP component must accept experiment_name parameter."""
        tm = TrainModel(trainer_image="img:latest")
        kfp_fn = tm.as_kfp_component()
        accepted = set(kfp_fn.component_spec.inputs or {})
        assert "experiment_name" in accepted

    def test_train_model_kfp_creates_experiment(self):
        """TrainModel KFP component must auto-create the experiment via aiplatform.init."""
        tm = TrainModel(trainer_image="img:latest")
        kfp_fn = tm.as_kfp_component()
        # The inner function source is embedded in the component spec
        source = kfp_fn.component_spec.implementation.container.command[-1]
        # Verify aiplatform.init receives experiment= so it auto-creates
        # (init with experiment= calls get_or_create internally)
        assert "aiplatform.init(" in source
        # Find the init call and verify it includes experiment=
        init_idx = source.index("aiplatform.init(")
        init_call = source[init_idx:source.index(")", init_idx) + 1]
        assert "experiment=experiment_name" in init_call

    def test_train_model_defaults(self):
        """TrainModel dataclass defaults."""
        tm = TrainModel(trainer_image="img:latest")
        assert tm.machine_type == "n1-standard-4"
        assert tm.accelerator_type == ""
        assert tm.accelerator_count == 0
        assert tm.trainer_args == []
        assert tm.hyperparameters == {}


class TestCompiler:
    def test_artifact_registry_resolved_in_trainer_image(self, test_context):
        """Compiler must resolve {artifact_registry} in trainer_image."""
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline = (
            PipelineBuilder(name="test-pipe", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .train(TrainModel(trainer_image="{artifact_registry}/my-trainer:latest"))
            .build()
        )
        compiler = PipelineCompiler()
        ctx_params = compiler._build_context_params(test_context, pipeline)
        train_step = pipeline.steps[1]
        step_params = compiler._step_params(train_step, ctx_params, run_date="2024-01-01")
        assert "{artifact_registry}" not in step_params["trainer_image"]
        assert "my-trainer:latest" in step_params["trainer_image"]

    def test_artifact_registry_resolved_in_serving_image(self, test_context):
        """Compiler must resolve {artifact_registry} in serving_container_image."""
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline = (
            PipelineBuilder(name="test-pipe", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .deploy(DeployModel(
                endpoint_name="ep",
                serving_container_image="{artifact_registry}/my-serving:latest",
            ))
            .build()
        )
        compiler = PipelineCompiler()
        ctx_params = compiler._build_context_params(test_context, pipeline)
        deploy_step = pipeline.steps[1]
        step_params = compiler._step_params(deploy_step, ctx_params, run_date="2024-01-01")
        assert "{artifact_registry}" not in step_params["serving_container_image"]
        assert "my-serving:latest" in step_params["serving_container_image"]


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
