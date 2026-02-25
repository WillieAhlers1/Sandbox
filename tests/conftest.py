"""Shared pytest fixtures."""

import pytest

from gcp_ml_framework.config import FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.naming import NamingConvention


@pytest.fixture
def naming_dev() -> NamingConvention:
    return NamingConvention(team="dsci", project="churn-pred", branch="feature/user-embeddings")


@pytest.fixture
def naming_main() -> NamingConvention:
    return NamingConvention(team="dsci", project="churn-pred", branch="main")


@pytest.fixture
def test_config() -> FrameworkConfig:
    return FrameworkConfig(
        team="test",
        project="myproj",
        branch="feature/test-branch",
        gcp=GCPConfig(
            dev_project_id="my-gcp-dev",
            staging_project_id="my-gcp-staging",
            prod_project_id="my-gcp-prod",
        ),
    )


@pytest.fixture
def test_context(test_config) -> MLContext:
    return MLContext.from_config(test_config)
