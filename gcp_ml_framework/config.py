"""
Layered configuration system for the GCP ML Framework.

Resolution order (later wins):
    framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags

All config is validated at load time via Pydantic. No silent defaults for
required GCP resource identifiers.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from gcp_ml_framework.naming import get_git_branch


class GitState(str, Enum):
    """The resolved environment driven by git branch/tag state."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"
    PROD_EXP = "prod_exp"


def _resolve_git_state(branch: str) -> GitState:
    """
    Derive the target environment from the git branch name.

    Rules:
        main            → STAGING
        prod/*          → PROD_EXP
        v[0-9]*         → PROD  (release tags; handled externally, but supported here)
        everything else → DEV
    """
    env_override = os.environ.get("GML_ENV_OVERRIDE", "").strip().lower()
    if env_override:
        return GitState(env_override)

    b = branch.lower()
    if b == "main":
        return GitState.STAGING
    if b.startswith("prod/"):
        return GitState.PROD_EXP
    if b.startswith("v") and b[1:2].isdigit():
        return GitState.PROD
    return GitState.DEV


class GCPConfig(BaseModel):
    dev_project_id: str = ""
    staging_project_id: str = ""
    prod_project_id: str = ""
    region: str = "us-central1"
    composer_env: str | None = None
    artifact_registry_host: str = "us-central1-docker.pkg.dev"
    service_account_email: str | None = None

    @field_validator("region")
    @classmethod
    def _only_us_central(cls, v: str) -> str:
        # Soft warning; enforcement left to Terraform for now.
        return v


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
        2. framework.yaml / pipeline/config.yaml
        3. GML_* environment variables
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
    gcp: GCPConfig = Field(default_factory=GCPConfig)
    feature_store: FeatureStoreConfig = Field(default_factory=FeatureStoreConfig)
    secrets: SecretsConfig = Field(default_factory=SecretsConfig)

    @model_validator(mode="after")
    def _validate_projects(self) -> "FrameworkConfig":
        state = _resolve_git_state(self.branch)
        # Only require the relevant project ID to be set.
        required = {
            GitState.DEV: ("dev_project_id", self.gcp.dev_project_id),
            GitState.STAGING: ("staging_project_id", self.gcp.staging_project_id),
            GitState.PROD: ("prod_project_id", self.gcp.prod_project_id),
            GitState.PROD_EXP: ("prod_project_id", self.gcp.prod_project_id),
        }
        field, value = required[state]
        if not value:
            raise ValueError(
                f"gcp.{field} must be set for git state '{state.value}' "
                f"(branch={self.branch!r}). Set it in framework.yaml or via "
                f"GML_GCP__{field.upper()}."
            )
        return self

    @property
    def git_state(self) -> GitState:
        return _resolve_git_state(self.branch)

    @property
    def active_gcp_project(self) -> str:
        """The GCP project ID for the current git state."""
        state = self.git_state
        mapping = {
            GitState.DEV: self.gcp.dev_project_id,
            GitState.STAGING: self.gcp.staging_project_id,
            GitState.PROD: self.gcp.prod_project_id,
            GitState.PROD_EXP: self.gcp.prod_project_id,
        }
        return mapping[state]


# ── Config loader ──────────────────────────────────────────────────────────────


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _find_framework_yaml() -> Path | None:
    """Walk up from cwd looking for framework.yaml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "framework.yaml"
        if candidate.exists():
            return candidate
    return None


def load_config(
    framework_yaml: Path | str | None = None,
    pipeline_yaml: Path | str | None = None,
    **overrides: Any,
) -> FrameworkConfig:
    """
    Load FrameworkConfig by merging YAML files + env vars + explicit overrides.

    Args:
        framework_yaml: Path to framework.yaml. Auto-discovered if None.
        pipeline_yaml:  Path to a pipeline-level config.yaml (optional).
        **overrides:    Keyword args that override everything (used by CLI).
    """
    # 1. Discover and load YAML files
    fw_path = Path(framework_yaml) if framework_yaml else _find_framework_yaml()
    base: dict[str, Any] = _load_yaml_file(fw_path) if fw_path else {}

    if pipeline_yaml:
        pipeline_data = _load_yaml_file(Path(pipeline_yaml))
        # Deep-merge pipeline config on top of framework config
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
