"""Unit tests for context.py — MLContext construction and properties."""

import pytest
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
