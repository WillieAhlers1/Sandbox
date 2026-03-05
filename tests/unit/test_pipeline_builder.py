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
        assert tm.machine_type == "n2-standard-4"
        assert tm.accelerator_type == ""
        assert tm.accelerator_count == 0
        assert tm.trainer_args == []
        assert tm.hyperparameters == {}

    def test_evaluate_model_reads_from_bq(self):
        """EvaluateModel KFP component must read data from BigQuery, not parquet."""
        em = EvaluateModel(gate={"auc": 0.75})
        kfp_fn = em.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        # Must use BigQuery client, not pd.read_parquet
        assert "bigquery.Client" in source
        assert "read_parquet" not in source

    def test_evaluate_model_loads_pickle_from_gcs(self):
        """EvaluateModel KFP component must download model.pkl from GCS and unpickle."""
        em = EvaluateModel(gate={"auc": 0.75})
        kfp_fn = em.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "model.pkl" in source
        assert "pickle.load" in source
        assert "storage.Client" in source

    def test_evaluate_model_uses_sklearn_metrics(self):
        """EvaluateModel KFP component must compute real metrics with sklearn."""
        em = EvaluateModel(gate={"auc": 0.75})
        kfp_fn = em.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "roc_auc_score" in source
        assert "f1_score" in source


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


    def test_evaluate_receives_dataset_not_model_uri(self, test_context):
        """evaluate-model's eval_dataset_uri must come from transform, not train."""
        import tempfile

        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline = (
            PipelineBuilder(name="test-pipe", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .transform(BQTransform(sql="SELECT * FROM raw", output_table="features"))
            .train(TrainModel(trainer_image="img:latest"))
            .evaluate(EvaluateModel(gate={"auc": 0.75}))
            .build()
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            compiler = PipelineCompiler(output_dir=tmpdir)
            yaml_path = compiler.compile(pipeline, test_context)
            yaml_content = yaml_path.read_text()

        # eval_dataset_uri should reference bq-transform's output, not train-model's
        # In KFP YAML, cross-step wiring uses taskOutputParameter references
        # The evaluate step should NOT have eval_dataset_uri pointing to train-model
        assert "eval_dataset_uri" in yaml_content
        # Find the evaluate-model task's inputs section
        import yaml as pyyaml

        compiled = pyyaml.safe_load(yaml_content)
        root = compiled.get("root", compiled)
        dag = root.get("dag", {})
        tasks = dag.get("tasks", {})
        eval_task = tasks.get("evaluate-model", {})
        eval_inputs = eval_task.get("inputs", {}).get("parameters", {})
        # eval_dataset_uri should reference bq-transform output
        eval_ds = eval_inputs.get("eval_dataset_uri", {})
        eval_ds_ref = eval_ds.get("taskOutputParameter", {})
        assert eval_ds_ref.get("producerTask") == "bq-transform", (
            f"eval_dataset_uri should come from bq-transform, got {eval_ds_ref}"
        )
        # model_uri should reference train-model output
        model_ref = eval_inputs.get("model_uri", {}).get("taskOutputParameter", {})
        assert model_ref.get("producerTask") == "train-model", (
            f"model_uri should come from train-model, got {model_ref}"
        )


    def test_deploy_registers_model_via_upload(self):
        """DeployModel KFP component must register model via aiplatform.Model.upload."""
        dm = DeployModel(endpoint_name="ep")
        kfp_fn = dm.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "Model.upload(" in source

    def test_deploy_receives_model_uri_from_train(self, test_context):
        """deploy-model's model_uri must come from train-model output in compiled YAML."""
        import tempfile

        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        pipeline = (
            PipelineBuilder(name="test-pipe", schedule="@daily")
            .ingest(BigQueryExtract(query="SELECT 1", output_table="raw"))
            .train(TrainModel(trainer_image="img:latest"))
            .deploy(DeployModel(endpoint_name="ep"))
            .build()
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            compiler = PipelineCompiler(output_dir=tmpdir)
            yaml_path = compiler.compile(pipeline, test_context)
            yaml_content = yaml_path.read_text()

        import yaml as pyyaml

        compiled = pyyaml.safe_load(yaml_content)
        root = compiled.get("root", compiled)
        dag = root.get("dag", {})
        tasks = dag.get("tasks", {})
        deploy_task = tasks.get("deploy-model", {})
        deploy_inputs = deploy_task.get("inputs", {}).get("parameters", {})
        model_ref = deploy_inputs.get("model_uri", {}).get("taskOutputParameter", {})
        assert model_ref.get("producerTask") == "train-model", (
            f"model_uri should come from train-model, got {model_ref}"
        )

    def test_example_churn_uses_prebuilt_serving_container(self):
        """Example churn pipeline must use Vertex AI pre-built sklearn serving container."""
        from pipelines.example_churn.pipeline import pipeline

        deploy_step = [s for s in pipeline.steps if s.stage == "deploy"][0]
        image = deploy_step.component.serving_container_image
        assert "vertex-ai/prediction/sklearn-cpu" in image, (
            f"Expected pre-built sklearn container, got {image}"
        )

    def test_serving_container_sklearn_version_gte_1_5(self):
        """Serving container must use sklearn >= 1.5 for numpy 2.x pickle compatibility."""
        from pipelines.example_churn.pipeline import pipeline

        deploy_step = [s for s in pipeline.steps if s.stage == "deploy"][0]
        image = deploy_step.component.serving_container_image
        # Extract version from image name like sklearn-cpu.1-5:latest
        import re

        match = re.search(r"sklearn-cpu\.(\d+)-(\d+)", image)
        assert match, f"Could not parse sklearn version from {image}"
        major, minor = int(match.group(1)), int(match.group(2))
        assert (major, minor) >= (1, 5), (
            f"Serving container sklearn {major}.{minor} < 1.5; numpy 2.x pickles will fail"
        )


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
