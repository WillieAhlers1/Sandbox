"""Shared test fixtures for the gcp_ml_framework test suite."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from gcp_ml_framework.config import FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.naming import NamingConvention


@pytest.fixture
def mock_naming() -> NamingConvention:
    return NamingConvention(
        team="testteam",
        project="testproject",
        branch="test-branch",
        gcp_project="test-gcp-project",
    )


@pytest.fixture
def mock_gcp_config() -> GCPConfig:
    return GCPConfig(
        dev_project_id="test-gcp-project",
        region="us-central1",
    )


@pytest.fixture
def mock_framework_config(mock_gcp_config: GCPConfig) -> FrameworkConfig:
    with patch.dict(os.environ, {"GML_ENVIRONMENT": "dev"}, clear=False):
        return FrameworkConfig(
            team="testteam",
            project="testproject",
            branch="test-branch",
            environment="dev",
            gcp=mock_gcp_config,
        )


@pytest.fixture
def mock_context(mock_framework_config: FrameworkConfig) -> MLContext:
    return MLContext.from_config(mock_framework_config)
