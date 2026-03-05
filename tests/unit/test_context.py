"""Unit tests for context.py — MLContext construction and properties."""

from gcp_ml_framework.config import GitState
from gcp_ml_framework.context import MLContext


class TestMLContext:
    def test_from_config(self, test_context):
        assert test_context.gcp_project == "my-gcp-dev"
        assert test_context.region == "us-central1"
        assert test_context.git_state == GitState.DEV

    def test_namespace_delegation(self, test_context):
        assert test_context.namespace == test_context.naming.namespace

    def test_bq_dataset_delegation(self, test_context):
        assert test_context.bq_dataset == test_context.naming.bq_dataset

    def test_gcs_prefix_delegation(self, test_context):
        assert test_context.gcs_prefix == test_context.naming.gcs_prefix

    def test_is_production_false_for_dev(self, test_context):
        assert not test_context.is_production()

    def test_is_production_true_for_prod(self):
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig
        cfg = FrameworkConfig(
            team="t", project="p", branch="v1.0.0",
            gcp=GCPConfig(dev_project_id="d", staging_project_id="s", prod_project_id="prod"),
        )
        ctx = MLContext.from_config(cfg)
        assert ctx.is_production()

    def test_secret_name(self, test_context):
        name = test_context.secret_name("db-password")
        assert "db-password" in name
        assert test_context.secret_prefix in name

    def test_summary_keys(self, test_context):
        summary = test_context.summary()
        for key in ("namespace", "gcp_project", "bq_dataset", "feature_store_id"):
            assert key in summary

    def test_raw_branch_preserved(self, test_context):
        assert test_context.raw_branch == "feature/test-branch"

    def test_pipeline_service_account_auto_derived_dev(self, test_context):
        """DEV context auto-derives pipeline SA from naming + git_state."""
        expected = "test-myproj-dev-pipeline@my-gcp-dev.iam.gserviceaccount.com"
        assert test_context.pipeline_service_account == expected

    def test_pipeline_service_account_auto_derived_staging(self):
        """STAGING context derives SA with staging env and staging project."""
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig
        cfg = FrameworkConfig(
            team="dsci", project="examplechurn", branch="main",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg-proj", prod_project_id="prd",
            ),
        )
        ctx = MLContext.from_config(cfg)
        expected = "dsci-examplechurn-staging-pipeline@stg-proj.iam.gserviceaccount.com"
        assert ctx.pipeline_service_account == expected

    def test_pipeline_service_account_auto_derived_prod(self):
        """PROD context derives SA with prod env and prod project."""
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig
        cfg = FrameworkConfig(
            team="dsci", project="examplechurn", branch="v2.0.0",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd-proj",
            ),
        )
        ctx = MLContext.from_config(cfg)
        expected = "dsci-examplechurn-prod-pipeline@prd-proj.iam.gserviceaccount.com"
        assert ctx.pipeline_service_account == expected

    def test_pipeline_service_account_explicit_override(self):
        """Explicit service_account_email overrides auto-derivation."""
        from gcp_ml_framework.config import FrameworkConfig, GCPConfig
        cfg = FrameworkConfig(
            team="t", project="p", branch="feat/x",
            gcp=GCPConfig(
                dev_project_id="dev",
                staging_project_id="stg",
                prod_project_id="prd",
                service_account_email="custom-sa@dev.iam.gserviceaccount.com",
            ),
        )
        ctx = MLContext.from_config(cfg)
        assert ctx.pipeline_service_account == "custom-sa@dev.iam.gserviceaccount.com"
