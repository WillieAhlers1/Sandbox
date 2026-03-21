"""Tests for gcp_ml_framework.config — Environment enum, FrameworkConfig, load_config."""

from __future__ import annotations

import os
from enum import StrEnum
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from gcp_ml_framework.config import Environment, FrameworkConfig, GCPConfig

pytestmark = pytest.mark.unit


# ── Environment enum ────────────────────────────────────────────────────────


class TestEnvironmentEnum:
    def test_environment_enum_values(self) -> None:
        """All 6 environment values exist and Environment is a StrEnum."""
        assert issubclass(Environment, StrEnum)
        expected = {"local", "dev", "test", "staging", "prod", "experiment"}
        actual = {e.value for e in Environment}
        assert actual == expected

    def test_environment_default_is_dev(self) -> None:
        """FrameworkConfig defaults environment to 'dev'."""
        env = {
            "GML_TEAM": "t",
            "GML_PROJECT": "p",
            "GML_BRANCH": "b",
            "GML_GCP__DEV_PROJECT_ID": "proj-dev",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t", project="p", branch="b",
                gcp=GCPConfig(dev_project_id="proj-dev"),
            )
        assert cfg.environment == "dev"

    def test_environment_from_env_var(self) -> None:
        """GML_ENVIRONMENT env var is picked up by FrameworkConfig."""
        env = {
            "GML_ENVIRONMENT": "staging",
            "GML_TEAM": "t",
            "GML_PROJECT": "p",
            "GML_BRANCH": "b",
            "GML_GCP__STAGING_PROJECT_ID": "proj-staging",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t", project="p", branch="b",
                gcp=GCPConfig(staging_project_id="proj-staging"),
            )
        assert cfg.environment == "staging"


# ── FrameworkConfig validation ──────────────────────────────────────────────


class TestFrameworkConfigValidation:
    def test_framework_config_validates_dev_project(self) -> None:
        """DEV environment requires gcp.dev_project_id to be set."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="dev_project_id"):
                FrameworkConfig(
                    team="t", project="p", branch="b",
                    environment="dev",
                    gcp=GCPConfig(),
                )

    def test_framework_config_validates_staging_project(self) -> None:
        """STAGING environment requires gcp.staging_project_id to be set."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="staging_project_id"):
                FrameworkConfig(
                    team="t", project="p", branch="b",
                    environment="staging",
                    gcp=GCPConfig(),
                )

    def test_framework_config_validates_prod_project(self) -> None:
        """PROD environment requires gcp.prod_project_id to be set."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValidationError, match="prod_project_id"):
                FrameworkConfig(
                    team="t", project="p", branch="b",
                    environment="prod",
                    gcp=GCPConfig(),
                )

    def test_framework_config_local_no_project_required(self) -> None:
        """LOCAL environment does not require any GCP project ID."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t", project="p", branch="b",
                environment="local",
                gcp=GCPConfig(),
            )
        assert cfg.environment == "local"


# ── active_gcp_project ──────────────────────────────────────────────────────


class TestActiveGCPProject:
    def test_active_gcp_project_dev(self) -> None:
        """DEV environment returns dev_project_id."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t", project="p", branch="b",
                environment="dev",
                gcp=GCPConfig(dev_project_id="my-dev-project"),
            )
        assert cfg.active_gcp_project == "my-dev-project"

    def test_active_gcp_project_test_fallback(self) -> None:
        """TEST environment falls back to dev_project_id when test_project_id is empty.

        The model_validator normally rejects an empty test_project_id for TEST,
        so we bypass validation via model_construct to exercise the fallback
        path in active_gcp_project.
        """
        gcp = GCPConfig(dev_project_id="fallback-dev", test_project_id="")
        cfg = FrameworkConfig.model_construct(
            team="t", project="p", branch="b",
            environment="test", gcp=gcp,
        )
        assert cfg.active_gcp_project == "fallback-dev"


# ── Misc ────────────────────────────────────────────────────────────────────


class TestMiscConfig:
    def test_branch_is_independent_of_environment(self) -> None:
        """Branch and environment are orthogonal — any combo is valid."""
        env = {"GML_TEAM": "t", "GML_PROJECT": "p", "GML_BRANCH": "b"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t", project="p", branch="feature/x",
                environment="staging",
                gcp=GCPConfig(staging_project_id="proj-stg"),
            )
        assert cfg.branch == "feature/x"
        assert cfg.environment == "staging"

    def test_no_resolve_git_state(self) -> None:
        """_resolve_git_state no longer exists as an importable name."""
        import gcp_ml_framework.config as config_mod

        assert not hasattr(config_mod, "_resolve_git_state")
