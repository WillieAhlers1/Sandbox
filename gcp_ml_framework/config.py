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
from pydantic import BaseModel, Field, model_validator
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


class GCPConfig(BaseModel):
    dev_project_id: str = ""
    test_project_id: str = ""
    staging_project_id: str = ""
    prod_project_id: str = ""
    region: str = "us-central1"
    composer_dags_path: dict[str, str] = Field(default_factory=dict)
    artifact_registry_host: str = ""
    pipeline_service_account_email: str | None = None
    composer_environment_name: str | None = None

    @model_validator(mode="after")
    def _derive_ar_host(self) -> GCPConfig:
        """Auto-derive artifact_registry_host from region when not explicitly set."""
        if not self.artifact_registry_host:
            self.artifact_registry_host = f"{self.region}-docker.pkg.dev"
        return self


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
        env_prefix="GML_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    team: str
    project: str
    branch: str = Field(default_factory=get_git_branch)
    environment: str = "dev"
    gcp: GCPConfig = Field(default_factory=GCPConfig)
    feature_store: FeatureStoreConfig = Field(default_factory=FeatureStoreConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    @model_validator(mode="after")
    def _validate_projects(self) -> FrameworkConfig:
        env = Environment(self.environment)
        # Only require the relevant project ID to be set.
        required = {
            Environment.LOCAL: None,
            Environment.DEV: ("dev_project_id", self.gcp.dev_project_id),
            Environment.TEST: ("test_project_id", self.gcp.test_project_id),
            Environment.STAGING: ("staging_project_id", self.gcp.staging_project_id),
            Environment.PROD: ("prod_project_id", self.gcp.prod_project_id),
            Environment.EXPERIMENT: ("prod_project_id", self.gcp.prod_project_id),
        }
        entry = required[env]
        if entry is not None:
            field, value = entry
            if not value:
                raise ValueError(
                    f"gcp.{field} must be set for environment '{env.value}'. "
                    f"Set via "
                    f"GML_GCP__{field.upper()}."
                )
        return self

    @property
    def active_gcp_project(self) -> str:
        """The GCP project ID for the current environment."""
        env = Environment(self.environment)
        mapping = {
            Environment.LOCAL: self.gcp.dev_project_id,
            Environment.DEV: self.gcp.dev_project_id,
            Environment.TEST: self.gcp.test_project_id or self.gcp.dev_project_id,
            Environment.STAGING: self.gcp.staging_project_id,
            Environment.PROD: self.gcp.prod_project_id,
            Environment.EXPERIMENT: self.gcp.prod_project_id,
        }
        return mapping[env]


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
