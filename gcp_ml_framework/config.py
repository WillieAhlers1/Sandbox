"""
Layered configuration system for the GCP ML Framework.

Resolution order (later wins):
    defaults → pipeline/config.yaml → env vars → CLI flags

All config is validated at load time via Pydantic. No silent defaults for
required GCP resource identifiers.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from gcp_ml_framework.naming import get_git_branch


class Environment(StrEnum):
    """Target deployment environment, set via GML_ENVIRONMENT."""

    LOCAL = "local"
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"
    EXPERIMENT = "experiment"


class GCPConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GCP_",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    project_id: str = Field(description="GCP Project ID")
    region: str = Field(description="GCP region")
    composer_dags_path: str = Field(default="", description="GCS path to Composer DAGs bucket")
    pipeline_service_account_email: str = Field(
        default="",
        description="Override pipeline SA email (blank = derive from naming)",
    )
    composer_environment_name: str = Field(
        default="",
        description="Override Composer environment name (blank = derive from naming)",
    )


class FeatureStoreConfig(BaseModel):
    """Vertex AI Feature Store — Bigtable-backed online serving."""

    online_serving_fixed_node_count: int = 1
    bigtable_min_node_count: int = 1
    # How frequently the BigQuery → online-store sync runs (cron).
    sync_schedule: str = "0 */6 * * *"


class SecretsConfig(BaseModel):
    """GCP Secret Manager integration."""

    project_id: str | None = None
    secret_prefix: str | None = None  # defaults to namespace at runtime


class FrameworkConfig(BaseSettings):
    """
    Primary config object. Loaded from:
        1. Built-in defaults (below)
        2. pipeline/config.yaml (optional)
        3. GML_* environment variables (via .env)
        4. Explicit keyword arguments

    Usage:
        cfg = FrameworkConfig()                          # auto-detect git branch
        cfg = FrameworkConfig(branch="feature/xyz")      # force branch
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    team: str = Field(alias="team", description="Team name")
    project: str = Field(alias="project", description="Project name")
    branch: str = Field(alias="branch", default_factory=get_git_branch, description="Git branch")
    environment: str = Field(alias="environment", description="Deployment environment")
    gcp: GCPConfig = Field(default_factory=GCPConfig, description="GCP configuration")  # type: ignore[arg-type]
    feature_store: FeatureStoreConfig = Field(
        default_factory=FeatureStoreConfig,
        description="Feature store configuration",
    )
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    @property
    def active_gcp_project(self) -> str:
        """The GCP project ID for the current environment."""
        return self.gcp.project_id


# ── Config loader ──────────────────────────────────────────────────────────────


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def load_config(
    pipeline_yaml: Path | str | None = None,
    **overrides: Any,
) -> FrameworkConfig:
    """
    Load FrameworkConfig by merging pipeline YAML + env vars + explicit overrides.

    Args:
        pipeline_yaml:  Path to a pipeline-level config.yaml (optional).
        **overrides:    Keyword args that override everything (used by CLI).
    """
    # 1. Start with empty base; load pipeline-level overrides if provided
    base: dict[str, Any] = {}

    if pipeline_yaml:
        pipeline_data = _load_yaml_file(Path(pipeline_yaml))
        for key, val in pipeline_data.items():
            if isinstance(val, dict) and isinstance(base.get(key), dict):
                base[key] = {**base[key], **val}
            else:
                base[key] = val

    # 2. Apply explicit overrides
    for key, val in overrides.items():
        base[key] = val

    # 3. Construct; env vars are picked up automatically by pydantic-settings
    return FrameworkConfig(**base)
