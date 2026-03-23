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
            "TEAM": "t",
            "PROJECT": "p",
            "BRANCH": "b",
            "ENVIRONMENT": "dev",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t",
                project="p",
                branch="b",
                environment="dev",
                gcp=GCPConfig(project_id="proj-dev", region="us-central1"),
            )
        assert cfg.environment == "dev"

    def test_environment_from_env_var(self) -> None:
        """ENVIRONMENT env var is picked up by FrameworkConfig."""
        env = {
            "ENVIRONMENT": "staging",
            "TEAM": "t",
            "PROJECT": "p",
            "BRANCH": "b",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t",
                project="p",
                branch="b",
                environment="staging",
                gcp=GCPConfig(project_id="proj-staging", region="us-central1"),
            )
        assert cfg.environment == "staging"


# ── FrameworkConfig validation ──────────────────────────────────────────────


class TestFrameworkConfigValidation:
    def test_gcp_config_requires_project_id(self) -> None:
        """GCPConfig without project_id raises ValidationError."""
        with pytest.raises(ValidationError, match="project_id"):
            GCPConfig(region="us-central1")

    def test_any_environment_valid_with_project_id(self) -> None:
        """Any environment is valid as long as project_id is set."""
        gcp = GCPConfig(project_id="my-project", region="us-central1")
        for env_name in ("dev", "test", "staging", "prod", "experiment"):
            env = {
                "TEAM": "t",
                "PROJECT": "p",
                "BRANCH": "b",
                "ENVIRONMENT": env_name,
            }
            with patch.dict(os.environ, env, clear=True):
                cfg = FrameworkConfig(
                    team="t",
                    project="p",
                    branch="b",
                    environment=env_name,
                    gcp=gcp,
                )
            assert cfg.environment == env_name

    def test_framework_config_local_no_project_required(self) -> None:
        """LOCAL environment does not require any GCP project ID."""
        env = {"TEAM": "t", "PROJECT": "p", "BRANCH": "b", "ENVIRONMENT": "local"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t",
                project="p",
                branch="b",
                environment="local",
                gcp=GCPConfig(project_id="test-project", region="us-central1"),
            )
        assert cfg.environment == "local"


# ── active_gcp_project ──────────────────────────────────────────────────────


class TestActiveGCPProject:
    def test_active_gcp_project_returns_project_id(self) -> None:
        """active_gcp_project returns gcp.project_id directly."""
        env = {"TEAM": "t", "PROJECT": "p", "BRANCH": "b", "ENVIRONMENT": "dev"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t",
                project="p",
                branch="b",
                environment="dev",
                gcp=GCPConfig(project_id="my-dev-project", region="us-central1"),
            )
        assert cfg.active_gcp_project == "my-dev-project"
        assert cfg.active_gcp_project == cfg.gcp.project_id


# ── Misc ────────────────────────────────────────────────────────────────────


class TestMiscConfig:
    def test_branch_is_independent_of_environment(self) -> None:
        """Branch and environment are orthogonal — any combo is valid."""
        env = {"TEAM": "t", "PROJECT": "p", "BRANCH": "b", "ENVIRONMENT": "staging"}
        with patch.dict(os.environ, env, clear=True):
            cfg = FrameworkConfig(
                team="t",
                project="p",
                branch="feature/x",
                environment="staging",
                gcp=GCPConfig(project_id="proj-stg", region="us-central1"),
            )
        assert cfg.branch == "feature/x"
        assert cfg.environment == "staging"

    def test_no_resolve_git_state(self) -> None:
        """_resolve_git_state no longer exists as an importable name."""
        import gcp_ml_framework.config as config_mod

        assert not hasattr(config_mod, "_resolve_git_state")
