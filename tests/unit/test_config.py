"""Unit tests for config.py — layered config and environment resolution."""

import pytest

from gcp_ml_framework.config import (
    FrameworkConfig,
    GCPConfig,
    GitState,
    _resolve_git_state,
)


class TestGitStateResolution:
    def test_feature_branch_is_dev(self):
        assert _resolve_git_state("feature/user-embeddings") == GitState.DEV

    def test_hotfix_is_dev(self):
        assert _resolve_git_state("hotfix/fix-null-values") == GitState.DEV

    def test_main_is_staging(self):
        assert _resolve_git_state("main") == GitState.STAGING

    def test_release_tag_is_prod(self):
        assert _resolve_git_state("v1.2.3") == GitState.PROD

    def test_prod_branch_is_prod_exp(self):
        assert _resolve_git_state("prod/experiment-xyz") == GitState.PROD_EXP

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("GML_ENV_OVERRIDE", "staging")
        assert _resolve_git_state("feature/anything") == GitState.STAGING


class TestFrameworkConfig:
    def test_basic_construction(self, test_config):
        assert test_config.team == "test"
        assert test_config.project == "myproj"

    def test_active_project_dev(self, test_config):
        assert test_config.active_gcp_project == "my-gcp-dev"

    def test_active_project_staging(self):
        cfg = FrameworkConfig(
            team="t",
            project="p",
            branch="main",
            gcp=GCPConfig(
                dev_project_id="dev",
                staging_project_id="staging",
                prod_project_id="prod",
            ),
        )
        assert cfg.active_gcp_project == "staging"

    def test_active_project_prod(self):
        cfg = FrameworkConfig(
            team="t",
            project="p",
            branch="v1.0.0",
            gcp=GCPConfig(
                dev_project_id="dev",
                staging_project_id="staging",
                prod_project_id="prod",
            ),
        )
        assert cfg.active_gcp_project == "prod"

    def test_missing_project_raises(self):
        with pytest.raises(ValueError):
            FrameworkConfig(
                team="t",
                project="p",
                branch="main",
                gcp=GCPConfig(
                    dev_project_id="dev",
                    staging_project_id="",   # missing!
                    prod_project_id="prod",
                ),
            )

    def test_default_region(self, test_config):
        assert test_config.gcp.region == "us-central1"

    def test_git_state_property(self, test_config):
        assert test_config.git_state == GitState.DEV

    # -- artifact_registry_host auto-derivation (Phase 1C) --

    def test_artifact_registry_host_auto_derived_from_region(self):
        """AR host defaults to {region}-docker.pkg.dev when not explicitly set."""
        cfg = FrameworkConfig(
            team="t", project="p", branch="test",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd",
                region="us-east4",
            ),
        )
        assert cfg.gcp.artifact_registry_host == "us-east4-docker.pkg.dev"

    def test_artifact_registry_host_auto_derived_default_region(self):
        """AR host derives correctly from the default region (us-central1)."""
        cfg = FrameworkConfig(
            team="t", project="p", branch="test",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd",
            ),
        )
        assert cfg.gcp.artifact_registry_host == "us-central1-docker.pkg.dev"

    def test_artifact_registry_host_explicit_override(self):
        """Explicit AR host is preserved even when region differs."""
        cfg = FrameworkConfig(
            team="t", project="p", branch="test",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd",
                region="us-east4",
                artifact_registry_host="us-docker.pkg.dev",
            ),
        )
        assert cfg.gcp.artifact_registry_host == "us-docker.pkg.dev"

    # -- composer_environment_name (Phase 3) --

    def test_composer_environment_name_default_none(self):
        """Composer env name defaults to None (auto-derived by runner)."""
        cfg = FrameworkConfig(
            team="t", project="p", branch="test",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd",
            ),
        )
        assert cfg.gcp.composer_environment_name is None

    def test_composer_environment_name_explicit(self):
        """Explicit Composer env name is preserved."""
        cfg = FrameworkConfig(
            team="t", project="p", branch="test",
            gcp=GCPConfig(
                dev_project_id="dev", staging_project_id="stg", prod_project_id="prd",
                composer_environment_name="mlopshousingpoc",
            ),
        )
        assert cfg.gcp.composer_environment_name == "mlopshousingpoc"
