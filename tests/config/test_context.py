"""Tests for gcp_ml_framework.context — MLContext creation, properties, and behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gcp_ml_framework.config import Environment, FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext

pytestmark = pytest.mark.unit


class TestContextCreation:
    def test_context_from_config(self, mock_context: MLContext) -> None:
        """MLContext.from_config creates an object with the expected fields."""
        assert mock_context.environment == Environment.DEV
        assert mock_context.gcp_project == "test-gcp-project"
        assert mock_context.region == "us-central1"
        assert mock_context.naming is not None

    def test_context_is_frozen(self, mock_context: MLContext) -> None:
        """Attempting to mutate a frozen MLContext raises an error."""
        with pytest.raises(ValidationError):
            mock_context.gcp_project = "other-project"


class TestContextPassthroughs:
    def test_context_namespace(
        self, mock_context: MLContext, mock_naming: object,
    ) -> None:
        """ctx.namespace passes through to naming.namespace."""
        assert mock_context.namespace == mock_context.naming.namespace

    def test_context_bq_dataset(self, mock_context: MLContext) -> None:
        """ctx.bq_dataset passes through to naming.bq_dataset."""
        assert mock_context.bq_dataset == mock_context.naming.bq_dataset

    def test_context_gcs_prefix(self, mock_context: MLContext) -> None:
        """ctx.gcs_prefix passes through to naming.gcs_prefix."""
        assert mock_context.gcs_prefix == mock_context.naming.gcs_prefix


class TestContextIsProduction:
    def test_context_is_production_true(self) -> None:
        """PROD and EXPERIMENT are considered production environments."""
        for env_name in ("prod", "experiment"):
            gcp = GCPConfig(prod_project_id="prod-proj")
            ctx = _make_context(environment=env_name, gcp=gcp)
            assert ctx.is_production(), f"{env_name} should be production"

    def test_context_is_production_false(self) -> None:
        """DEV, LOCAL, TEST, STAGING are NOT production."""
        non_prod = {
            "dev": GCPConfig(dev_project_id="p"),
            "local": GCPConfig(),
            "test": GCPConfig(test_project_id="p"),
            "staging": GCPConfig(staging_project_id="p"),
        }
        for env_name, gcp in non_prod.items():
            ctx = _make_context(environment=env_name, gcp=gcp)
            assert not ctx.is_production(), f"{env_name} should NOT be production"


class TestContextServiceAccount:
    def test_context_pipeline_service_account(self, mock_context: MLContext) -> None:
        """When no SA is explicitly set, pipeline_service_account is derived from naming."""
        sa = mock_context.pipeline_service_account
        assert sa == (
            f"{mock_context.naming.team}-{mock_context.naming.project}"
            f"-{mock_context.environment.value}-pipeline"
            f"@{mock_context.gcp_project}.iam.gserviceaccount.com"
        )


class TestContextSummary:
    def test_context_summary_keys(self, mock_context: MLContext) -> None:
        """summary() returns a dict with all expected display keys."""
        summary = mock_context.summary()
        expected_keys = {
            "team", "project", "branch (raw)", "branch (slug)",
            "environment", "gcp_project", "region", "namespace",
            "gcs_bucket", "gcs_prefix", "bq_dataset",
            "feature_store_id", "secret_prefix", "composer_dags_path",
        }
        assert set(summary.keys()) == expected_keys


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_context(
    environment: str,
    gcp: GCPConfig | None = None,
    team: str = "t",
    project: str = "p",
    branch: str = "b",
) -> MLContext:
    """Build an MLContext for the given environment without touching real env vars."""
    import os
    from unittest.mock import patch

    gcp = gcp or GCPConfig(dev_project_id="dummy")
    env_vars = {
        "GML_TEAM": team,
        "GML_PROJECT": project,
        "GML_BRANCH": branch,
    }
    with patch.dict(os.environ, env_vars, clear=True):
        cfg = FrameworkConfig(
            team=team, project=project, branch=branch,
            environment=environment, gcp=gcp,
        )
    return MLContext.from_config(cfg)
