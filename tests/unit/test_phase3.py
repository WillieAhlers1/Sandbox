"""Phase 3 TDD tests — Feature Store v2, model versioning, experiment tracking."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from gcp_ml_framework.components.feature_store.write_features import ReadFeatures, WriteFeatures
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.train import TrainModel


# ═══════════════════════════════════════════════════════════════════════
# 3.1 Feature Store Client — v2 APIs
# ═══════════════════════════════════════════════════════════════════════


class TestFeatureStoreClientV2:
    def test_client_uses_feature_group_api(self):
        """Client must use v2 FeatureGroup (not v1 EntityType)."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        source = FeatureStoreClient.__module__
        import importlib
        mod = importlib.import_module(source)
        src = Path(mod.__file__).read_text()
        # v2 uses FeatureGroup, not EntityType
        assert "FeatureGroup" in src or "feature_group" in src
        # Should not use old v1 EntityType create methods
        assert "create_entity_type" not in src

    def test_client_has_ensure_feature_group(self):
        """Client must have an ensure_feature_group method."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        assert hasattr(FeatureStoreClient, "ensure_feature_group")

    def test_client_has_ensure_feature_view(self):
        """Client must have an ensure_feature_view method."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        assert hasattr(FeatureStoreClient, "ensure_feature_view")

    def test_client_no_v1_featurestore_class(self):
        """Client must not use v1 aiplatform.Featurestore class."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        import importlib
        mod = importlib.import_module(FeatureStoreClient.__module__)
        src = Path(mod.__file__).read_text()
        assert "aiplatform.Featurestore(" not in src

    def test_ensure_feature_group_mocked(self, test_context):
        """ensure_feature_group registers a BQ table (mocked)."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        client = FeatureStoreClient(test_context)
        with patch.object(client, "_create_or_get_feature_group") as mock_create:
            mock_create.return_value = MagicMock()
            result = client.ensure_feature_group(
                name="user_behavioral",
                bq_table=f"{test_context.gcp_project}.{test_context.bq_dataset}.churn_features",
            )
            mock_create.assert_called_once()

    def test_ensure_feature_view_mocked(self, test_context):
        """ensure_feature_view creates serving connection (mocked)."""
        from gcp_ml_framework.feature_store.client import FeatureStoreClient

        client = FeatureStoreClient(test_context)
        with patch.object(client, "_create_or_get_feature_view") as mock_create:
            mock_create.return_value = MagicMock()
            result = client.ensure_feature_view(
                entity="user",
                feature_group="behavioral",
                bq_source_table=f"{test_context.gcp_project}.{test_context.bq_dataset}.churn_features",
            )
            mock_create.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# 3.2 WriteFeatures — metadata-only (no gRPC, no LRO)
# ═══════════════════════════════════════════════════════════════════════


class TestWriteFeaturesSimplified:
    def test_write_features_no_grpc_import(self):
        """WriteFeatures KFP component must not use gRPC FeaturestoreServiceClient."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        kfp_fn = wf.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "FeaturestoreServiceClient" not in source
        assert "ImportFeatureValuesRequest" not in source

    def test_write_features_no_lro_polling(self):
        """WriteFeatures KFP component must not poll LRO (no time.sleep loop)."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        kfp_fn = wf.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "time.sleep" not in source
        assert "operations_client" not in source

    def test_write_features_is_metadata_only(self):
        """WriteFeatures KFP component registers FeatureGroup metadata."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        kfp_fn = wf.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        # Should use v2 FeatureGroup registration
        assert "FeatureGroup" in source or "feature_group" in source

    def test_write_features_local_run_no_crash(self, test_context):
        """WriteFeatures local_run should not crash."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        wf.local_run(test_context)


# ═══════════════════════════════════════════════════════════════════════
# 3.3 ReadFeatures — returns real data from DuckDB
# ═══════════════════════════════════════════════════════════════════════


class TestReadFeaturesFixed:
    def test_read_features_local_run_returns_data(self, test_context):
        """ReadFeatures.local_run() should return actual data, not empty DataFrame."""
        import pandas as pd

        conn = duckdb.connect()
        dataset = test_context.bq_dataset
        conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
        conn.sql(
            f'CREATE TABLE "{dataset}"."feat_user_behavioral" AS '
            f"SELECT 'u1' AS entity_id, 10 AS session_count_7d, 45 AS session_count_30d"
        )

        rf = ReadFeatures(
            entity="user",
            feature_group="behavioral",
            feature_ids=["session_count_7d", "session_count_30d"],
        )
        result = rf.local_run(test_context, db_conn=conn)
        # Should return a path to a non-empty parquet file
        assert isinstance(result, str)
        assert result.endswith(".parquet")
        df = pd.read_parquet(result)
        assert len(df) > 0
        assert "session_count_7d" in df.columns

    def test_read_features_local_run_reads_from_duckdb(self, test_context):
        """ReadFeatures should read from DuckDB table matching the feature group."""
        import pandas as pd

        conn = duckdb.connect()
        dataset = test_context.bq_dataset
        conn.sql(f'CREATE SCHEMA IF NOT EXISTS "{dataset}"')
        conn.sql(
            f'CREATE TABLE "{dataset}"."feat_user_behavioral" AS '
            f"SELECT 'u1' AS entity_id, 5 AS logins UNION ALL "
            f"SELECT 'u2' AS entity_id, 12 AS logins"
        )

        rf = ReadFeatures(
            entity="user",
            feature_group="behavioral",
            feature_ids=["logins"],
        )
        result = rf.local_run(test_context, db_conn=conn)
        df = pd.read_parquet(result)
        assert len(df) == 2


# ═══════════════════════════════════════════════════════════════════════
# 3.4 Model Versioning
# ═══════════════════════════════════════════════════════════════════════


class TestModelVersioning:
    def test_train_model_versioned_output_path(self, test_context):
        """TrainModel local_run output should include pipeline name and run_id."""
        tm = TrainModel(machine_type="n2-standard-4")
        result = tm.local_run(
            test_context,
            pipeline_name="churn_prediction",
            run_id="20240601_abc123",
        )
        # Output directory should contain pipeline_name and run_id
        assert "churn_prediction" in result
        assert "20240601_abc123" in result

    def test_train_model_kfp_uses_versioned_path(self):
        """TrainModel KFP component should use versioned model output path."""
        tm = TrainModel(machine_type="n2-standard-4")
        kfp_fn = tm.as_kfp_component()
        # KFP component should accept run_id parameter
        accepted = set(kfp_fn.component_spec.inputs or {})
        assert "run_id" in accepted

    def test_train_model_local_writes_model_file(self, test_context):
        """TrainModel local_run should write a model file."""
        tm = TrainModel(machine_type="n2-standard-4")
        result = tm.local_run(
            test_context,
            pipeline_name="churn_prediction",
            run_id="test_run",
        )
        model_path = Path(result) / "model.json"
        assert model_path.exists()


# ═══════════════════════════════════════════════════════════════════════
# 3.5 Experiment Tracking
# ═══════════════════════════════════════════════════════════════════════


class TestExperimentTracking:
    def test_evaluate_kfp_logs_metrics(self):
        """EvaluateModel KFP component must call aiplatform.log_metrics()."""
        em = EvaluateModel(gate={"auc": 0.75})
        kfp_fn = em.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "log_metrics" in source

    def test_evaluate_kfp_initializes_experiment(self):
        """EvaluateModel KFP component must initialize experiment for logging."""
        em = EvaluateModel(gate={"auc": 0.75})
        kfp_fn = em.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        # Should init aiplatform with experiment context
        assert "aiplatform.init(" in source
        assert "experiment" in source


# ═══════════════════════════════════════════════════════════════════════
# Phase 3 DoD cross-checks
# ═══════════════════════════════════════════════════════════════════════


class TestPhase3DoD:
    def test_write_features_no_10_minute_wait(self):
        """WriteFeatures must not have 10-minute polling loop."""
        wf = WriteFeatures(entity="user", feature_group="behavioral")
        kfp_fn = wf.as_kfp_component()
        source = kfp_fn.component_spec.implementation.container.command[-1]
        assert "range(60)" not in source
        assert "10 minutes" not in source
