"""Phase 5 — Component unit tests.

Tests each component's:
- Parameter validation and defaults
- local_run() logic with seed data and DuckDB
- as_kfp_component() returns a valid callable
"""

import json
import os

import duckdb
import pandas as pd
import pytest

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.ingestion.gcs_extract import GCSExtract
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import (
    ReadFeatures,
    WriteFeatures,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def conn():
    """Shared DuckDB connection for tests."""
    c = duckdb.connect()
    yield c
    c.close()


@pytest.fixture
def seeded_conn(conn, test_context):
    """DuckDB connection with a sample table for SQL-based components."""
    dataset = test_context.bq_dataset
    conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
    conn.sql(
        f'CREATE TABLE "{dataset}"."raw_events" AS '
        "SELECT 1 AS user_id, 'click' AS event_type, 42 AS value"
    )
    return conn


# ── ComponentConfig ───────────────────────────────────────────────────────────


class TestComponentConfig:
    def test_defaults(self):
        cfg = ComponentConfig()
        assert cfg.machine_type == "n2-standard-4"
        assert cfg.accelerator_type is None
        assert cfg.accelerator_count == 0
        assert cfg.timeout_seconds == 3600
        assert cfg.retry_count == 1
        assert cfg.cache_enabled is True

    def test_custom_values(self):
        cfg = ComponentConfig(
            machine_type="n2-standard-8",
            accelerator_type="NVIDIA_TESLA_T4",
            accelerator_count=1,
        )
        assert cfg.machine_type == "n2-standard-8"
        assert cfg.accelerator_type == "NVIDIA_TESLA_T4"
        assert cfg.accelerator_count == 1


# ── BigQueryExtract ───────────────────────────────────────────────────────────


class TestBigQueryExtract:
    def test_defaults(self):
        comp = BigQueryExtract(
            query="SELECT * FROM t", output_table="test_out"
        )
        assert comp.component_name == "bigquery_extract"
        assert comp.write_disposition == "WRITE_TRUNCATE"

    def test_is_base_component(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        assert isinstance(comp, BaseComponent)

    def test_as_kfp_component_returns_callable(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_with_duckdb(self, test_context, seeded_conn):
        comp = BigQueryExtract(
            query='SELECT * FROM "{bq_dataset}"."raw_events"',
            output_table="raw_extract",
        )
        result = comp.local_run(test_context, db_conn=seeded_conn)
        assert result.endswith(".parquet")
        assert os.path.exists(result)
        df = pd.read_parquet(result)
        assert len(df) == 1
        assert "user_id" in df.columns

    def test_local_run_template_substitution(self, test_context, seeded_conn):
        comp = BigQueryExtract(
            query='SELECT * FROM "{bq_dataset}"."raw_events" WHERE 1=1',
            output_table="template_test",
        )
        result = comp.local_run(test_context, run_date="2024-06-01", db_conn=seeded_conn)
        assert os.path.exists(result)

    def test_repr(self):
        comp = BigQueryExtract(query="SELECT 1", output_table="t")
        assert "BigQueryExtract" in repr(comp)
        assert "bigquery_extract" in repr(comp)


# ── GCSExtract ────────────────────────────────────────────────────────────────


class TestGCSExtract:
    def test_defaults(self):
        comp = GCSExtract(source_uri="gs://bucket/path", destination_folder="raw")
        assert comp.component_name == "gcs_extract"

    def test_as_kfp_component_returns_callable(self):
        comp = GCSExtract(source_uri="gs://b/p", destination_folder="raw")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_creates_directory(self, test_context):
        comp = GCSExtract(source_uri="gs://b/p", destination_folder="raw_data")
        result = comp.local_run(test_context)
        assert os.path.isdir(result)
        assert "raw_data" in result


# ── BQTransform ───────────────────────────────────────────────────────────────


class TestBQTransform:
    def test_requires_sql_or_sql_file(self):
        with pytest.raises(ValueError, match="requires either sql_file or sql"):
            BQTransform(output_table="t")

    def test_inline_sql(self):
        comp = BQTransform(sql="SELECT 1 AS x", output_table="t")
        assert comp.component_name == "bq_transform"
        assert comp._get_sql() == "SELECT 1 AS x"

    def test_sql_file(self, tmp_path):
        sql_file = tmp_path / "transform.sql"
        sql_file.write_text("SELECT 42 AS answer")
        comp = BQTransform(sql_file=str(sql_file), output_table="t")
        assert comp._get_sql() == "SELECT 42 AS answer"

    def test_sql_file_not_found(self):
        comp = BQTransform(sql_file="/nonexistent/file.sql", output_table="t")
        with pytest.raises(FileNotFoundError):
            comp._get_sql()

    def test_as_kfp_component_returns_callable(self):
        comp = BQTransform(sql="SELECT 1", output_table="t")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_with_inline_sql(self, test_context, conn):
        comp = BQTransform(sql="SELECT 1 AS x, 'hello' AS y", output_table="transform_out")
        result = comp.local_run(test_context, db_conn=conn)
        assert result.endswith(".parquet")
        df = pd.read_parquet(result)
        assert len(df) == 1
        assert df["x"].iloc[0] == 1

    def test_local_run_with_sql_file(self, test_context, conn, tmp_path):
        sql_file = tmp_path / "test.sql"
        sql_file.write_text("SELECT 99 AS val")
        comp = BQTransform(sql_file=str(sql_file), output_table="file_out")
        result = comp.local_run(test_context, db_conn=conn)
        df = pd.read_parquet(result)
        assert df["val"].iloc[0] == 99


# ── WriteFeatures ─────────────────────────────────────────────────────────────


class TestWriteFeatures:
    def test_defaults(self):
        comp = WriteFeatures(
            entity="user", feature_group="behavioral", entity_id_column="user_id"
        )
        assert comp.component_name == "write_features"
        assert comp.feature_time_column == "feature_timestamp"
        assert comp.feature_ids == []

    def test_as_kfp_component_returns_callable(self):
        comp = WriteFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_with_parquet_input(self, test_context, tmp_path):
        # Create a sample parquet file
        df = pd.DataFrame({"user_id": [1, 2], "feature_a": [0.5, 0.8]})
        input_path = str(tmp_path / "features.parquet")
        df.to_parquet(input_path)

        comp = WriteFeatures(entity="user", feature_group="signals")
        # local_run returns None for WriteFeatures
        comp.local_run(test_context, input_path=input_path)

    def test_local_run_no_input(self, test_context):
        comp = WriteFeatures(entity="user", feature_group="signals")
        comp.local_run(test_context)


# ── ReadFeatures ──────────────────────────────────────────────────────────────


class TestReadFeatures:
    def test_defaults(self):
        comp = ReadFeatures(entity="user", feature_group="behavioral")
        assert comp.component_name == "read_features"
        assert comp.output_table == "features_read"
        assert comp.feature_ids == []

    def test_as_kfp_component_returns_callable(self):
        comp = ReadFeatures(entity="user", feature_group="behavioral")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_with_duckdb(self, test_context, conn):
        dataset = test_context.bq_dataset
        conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
        conn.sql(
            f'CREATE TABLE "{dataset}"."feat_user_behavioral" AS '
            "SELECT 'u1' AS entity_id, 5 AS session_count_7d, 2.5 AS purchase_total"
        )

        comp = ReadFeatures(entity="user", feature_group="behavioral")
        result = comp.local_run(test_context, db_conn=conn)
        assert result.endswith(".parquet")
        df = pd.read_parquet(result)
        assert len(df) == 1
        assert "session_count_7d" in df.columns

    def test_local_run_with_feature_ids(self, test_context, conn):
        dataset = test_context.bq_dataset
        conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
        conn.sql(
            f'CREATE TABLE "{dataset}"."feat_user_demo" AS '
            "SELECT 'u1' AS entity_id, 30 AS age, 'US' AS country"
        )

        comp = ReadFeatures(
            entity="user", feature_group="demo", feature_ids=["age"]
        )
        result = comp.local_run(test_context, db_conn=conn)
        df = pd.read_parquet(result)
        assert "age" in df.columns

    def test_local_run_no_db_conn(self, test_context):
        comp = ReadFeatures(entity="user", feature_group="behavioral")
        result = comp.local_run(test_context)
        assert result.endswith(".parquet")
        df = pd.read_parquet(result)
        assert len(df) == 0  # empty DataFrame when no db_conn

    def test_local_run_missing_table(self, test_context, conn):
        comp = ReadFeatures(entity="user", feature_group="nonexistent")
        result = comp.local_run(test_context, db_conn=conn)
        df = pd.read_parquet(result)
        assert len(df) == 0  # gracefully returns empty


# ── TrainModel ────────────────────────────────────────────────────────────────


class TestTrainModel:
    def test_defaults(self):
        comp = TrainModel()
        assert comp.component_name == "train_model"
        assert comp.trainer_image == ""
        assert comp.machine_type == "n2-standard-4"
        assert comp.accelerator_type == ""
        assert comp.accelerator_count == 0

    def test_as_kfp_component_returns_callable(self):
        comp = TrainModel(trainer_image="gcr.io/project/trainer:latest")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_creates_model_artifact(self, test_context):
        comp = TrainModel(hyperparameters={"lr": 0.01, "epochs": 10})
        result = comp.local_run(test_context, pipeline_name="test_pipe", run_id="run-001")
        assert os.path.isdir(result)
        # Versioned path: {pipeline_name}/{run_id}/
        assert "test_pipe" in result
        assert "run-001" in result
        model_file = os.path.join(result, "model.json")
        assert os.path.exists(model_file)
        with open(model_file) as f:
            data = json.load(f)
        assert data["hyperparameters"]["lr"] == 0.01
        assert data["pipeline_name"] == "test_pipe"

    def test_resolve_image_uri_explicit(self, test_context):
        comp = TrainModel(trainer_image="gcr.io/my-proj/trainer:v1")
        uri = comp.resolve_image_uri("my_pipeline", test_context)
        assert uri == "gcr.io/my-proj/trainer:v1"

    def test_resolve_image_uri_auto(self, test_context):
        comp = TrainModel()  # no trainer_image
        uri = comp.resolve_image_uri("churn_prediction", test_context)
        assert "churn-prediction-trainer" in uri

    def test_resolve_image_uri_with_pipeline_dir(self, test_context):
        """pipeline_dir name is used instead of pipeline_name for image derivation."""
        from pathlib import Path

        comp = TrainModel()
        uri = comp.resolve_image_uri(
            "reco_training", test_context,
            pipeline_dir=Path("pipelines/recommendation_engine"),
        )
        assert "recommendation-engine-trainer" in uri
        assert "reco-training" not in uri


# ── EvaluateModel ─────────────────────────────────────────────────────────────


class TestEvaluateModel:
    def test_defaults(self):
        comp = EvaluateModel()
        assert comp.component_name == "evaluate_model"
        assert comp.metrics == ["auc"]
        assert comp.gate == {}

    def test_custom_metrics_and_gate(self):
        comp = EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.8})
        assert comp.metrics == ["auc", "f1"]
        assert comp.gate["auc"] == 0.8

    def test_as_kfp_component_returns_callable(self):
        comp = EvaluateModel()
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_placeholder_metrics(self, test_context):
        comp = EvaluateModel(metrics=["auc", "f1", "accuracy"])
        result = comp.local_run(test_context)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"auc", "f1", "accuracy"}
        # All placeholder values are 0.50
        assert all(v == 0.50 for v in result.values())

    def test_local_run_gate_pass(self, test_context):
        comp = EvaluateModel(
            metrics=["auc"], gate={"auc": 0.40}  # 0.50 > 0.40, passes
        )
        result = comp.local_run(test_context)
        assert result["auc"] == 0.50

    def test_local_run_gate_fail(self, test_context):
        comp = EvaluateModel(
            metrics=["auc"], gate={"auc": 0.90}  # 0.50 < 0.90, fails
        )
        with pytest.raises(ValueError, match="Gate failures"):
            comp.local_run(test_context)

    def test_local_run_multiple_gates(self, test_context):
        comp = EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.90, "f1": 0.80},
        )
        with pytest.raises(ValueError, match="Gate failures") as exc_info:
            comp.local_run(test_context)
        # Both metrics should fail
        assert "auc" in str(exc_info.value)
        assert "f1" in str(exc_info.value)


# ── DeployModel ───────────────────────────────────────────────────────────────


class TestDeployModel:
    def test_defaults(self):
        comp = DeployModel(endpoint_name="churn-v1")
        assert comp.component_name == "deploy_model"
        assert comp.machine_type == "n2-standard-2"
        assert comp.min_replica_count == 1
        assert comp.max_replica_count == 3
        assert comp.traffic_split == {"new": 100}

    def test_canary_traffic_split(self):
        comp = DeployModel(
            endpoint_name="churn-v1",
            traffic_split={"new": 10, "current": 90},
        )
        assert comp.traffic_split["new"] == 10
        assert comp.traffic_split["current"] == 90

    def test_as_kfp_component_returns_callable(self):
        comp = DeployModel(endpoint_name="test")
        fn = comp.as_kfp_component()
        assert callable(fn)

    def test_local_run_returns_endpoint_stub(self, test_context):
        comp = DeployModel(endpoint_name="churn-v1")
        result = comp.local_run(test_context, model_path="/tmp/model")
        assert "endpoints/local-stub" in result
        assert test_context.gcp_project in result
