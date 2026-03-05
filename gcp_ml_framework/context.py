"""
MLContext — the single runtime object passed to every component and DAG.

No component should import FrameworkConfig directly; it receives MLContext.
This keeps components decoupled from config loading and testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gcp_ml_framework.config import FrameworkConfig, GitState
from gcp_ml_framework.naming import NamingConvention


@dataclass(frozen=True)
class MLContext:
    """
    Immutable runtime context derived from FrameworkConfig + NamingConvention.

    All GCP resource names are available via `ctx.naming.*`.
    The active GCP project for the current git state is `ctx.gcp_project`.

    Usage:
        ctx = MLContext.from_config(cfg)
        ctx.naming.bq_dataset        # branch-namespaced BQ dataset
        ctx.naming.gcs_prefix        # gs://{bucket}/{branch}/
        ctx.gcp_project              # resolved GCP project ID
        ctx.git_state                # GitState.DEV | STAGING | PROD | PROD_EXP
    """

    naming: NamingConvention
    gcp_project: str
    region: str
    git_state: GitState
    composer_dags_path: dict[str, str]
    artifact_registry_host: str
    service_account_email: str | None
    feature_store_online_node_count: int
    secret_project_id: str
    secret_prefix: str
    # Raw branch for display; naming.branch is the sanitized slug
    raw_branch: str = field(compare=False)

    @classmethod
    def from_config(cls, cfg: FrameworkConfig) -> MLContext:
        naming = NamingConvention(
            team=cfg.team,
            project=cfg.project,
            branch=cfg.branch,
        )
        gcp_project = cfg.active_gcp_project
        secret_prefix = cfg.secrets.secret_prefix or naming.namespace

        return cls(
            naming=naming,
            gcp_project=gcp_project,
            region=cfg.gcp.region,
            git_state=cfg.git_state,
            composer_dags_path=cfg.gcp.composer_dags_path,
            artifact_registry_host=cfg.gcp.artifact_registry_host,
            service_account_email=cfg.gcp.service_account_email,
            feature_store_online_node_count=cfg.feature_store.online_serving_fixed_node_count,
            secret_project_id=cfg.secrets.project_id or gcp_project,
            secret_prefix=secret_prefix,
            raw_branch=cfg.branch,
        )

    # Convenience pass-throughs ---------------------------------------------------

    @property
    def namespace(self) -> str:
        return self.naming.namespace

    @property
    def bq_dataset(self) -> str:
        return self.naming.bq_dataset

    @property
    def gcs_prefix(self) -> str:
        return self.naming.gcs_prefix

    @property
    def feature_store_id(self) -> str:
        return self.naming.feature_store_id

    def secret_name(self, key: str) -> str:
        """Returns the fully-qualified Secret Manager secret name for a key."""
        return f"{self.secret_prefix}-{key}"

    def is_production(self) -> bool:
        return self.git_state in (GitState.PROD, GitState.PROD_EXP)

    def summary(self) -> dict[str, str]:
        """Human-readable summary for `gml context show`."""
        return {
            "team": self.naming.team,
            "project": self.naming.project,
            "branch (raw)": self.raw_branch,
            "branch (slug)": self.naming.branch,
            "git_state": self.git_state.value,
            "gcp_project": self.gcp_project,
            "region": self.region,
            "namespace": self.namespace,
            "gcs_bucket": self.naming.gcs_bucket,
            "gcs_prefix": self.gcs_prefix,
            "bq_dataset": self.bq_dataset,
            "feature_store_id": self.feature_store_id,
            "secret_prefix": self.secret_prefix,
            "composer_dags_path": str(self.composer_dags_path) if self.composer_dags_path else "(not configured)",
        }
