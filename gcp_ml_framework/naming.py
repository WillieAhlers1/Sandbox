"""
Namespace resolution and GCP resource naming.

All GCP resource names are derived from the canonical namespace token:
    {team}-{project}-{branch}

This module is the single source of truth for every resource name in the
framework. No resource name should ever be constructed outside this module.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import cached_property

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_BQ_RE = re.compile(r"[^a-z0-9_]+")


def _slugify(value: str, max_len: int = 30) -> str:
    """Lowercase, replace non-alphanumeric runs with hyphens, truncate."""
    return _SLUG_RE.sub("-", value.lower()).strip("-")[:max_len]


def _bq_safe(value: str, max_len: int = 30) -> str:
    """Lowercase, replace non-alphanumeric chars with underscores, truncate."""
    return _BQ_RE.sub("_", value.lower()).strip("_")[:max_len]


def get_git_branch() -> str:
    """Detect the current git branch. Returns 'local' if detection fails."""
    try:
        result = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        return result.decode().strip()
    except Exception:
        return "local"


def get_git_sha(short: bool = True) -> str:
    """Return the current git commit SHA."""
    try:
        args = ["git", "rev-parse", "--short" if short else "", "HEAD"]
        result = subprocess.check_output(
            [a for a in args if a], stderr=subprocess.DEVNULL
        )
        return result.decode().strip()
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class NamingConvention:
    """
    Derives all GCP resource names from team, project, and branch.

    Usage:
        nc = NamingConvention(team="dsci", project="churn-pred", branch="feature/xyz")
        nc.namespace          # "dsci-churn-pred-feature-xyz"
        nc.bq_dataset         # "dsci_churn_pred_feature_xyz"
        nc.gcs_prefix         # "gs://dsci-churn-pred/feature-xyz/"
    """

    team: str
    project: str
    branch: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", _slugify(self.team, 12))
        object.__setattr__(self, "project", _slugify(self.project, 20))
        object.__setattr__(self, "branch", _slugify(self.branch, 30))

    # ── Core namespace ────────────────────────────────────────────────────────

    @cached_property
    def namespace(self) -> str:
        """Canonical namespace token: {team}-{project}-{branch}."""
        return f"{self.team}-{self.project}-{self.branch}"

    @cached_property
    def namespace_bq(self) -> str:
        """BigQuery-safe namespace (underscores only)."""
        return _bq_safe(self.namespace)

    # ── GCS ──────────────────────────────────────────────────────────────────

    @cached_property
    def gcs_bucket(self) -> str:
        """Shared GCS bucket for the team+project (branches share the bucket)."""
        return f"{self.team}-{self.project}"

    @cached_property
    def gcs_prefix(self) -> str:
        """GCS path prefix for this branch: gs://{bucket}/{branch}/"""
        return f"gs://{self.gcs_bucket}/{self.branch}/"

    def gcs_path(self, *parts: str) -> str:
        """Build a GCS URI under this branch's prefix."""
        return self.gcs_prefix + "/".join(parts)

    def gcs_pipeline_root(self, pipeline_name: str) -> str:
        return self.gcs_path("pipelines", pipeline_name)

    def gcs_data_path(self, stage: str, dataset: str) -> str:
        """stage: 'raw' | 'staging' | 'processed' | 'features'"""
        return self.gcs_path("data", stage, dataset)

    def gcs_model_path(self, model_name: str, version: str = "latest") -> str:
        return self.gcs_path("models", model_name, version)

    # ── BigQuery ──────────────────────────────────────────────────────────────

    @cached_property
    def bq_dataset(self) -> str:
        """Branch-specific BQ dataset (underscored, max 1024 chars but we keep ≤63)."""
        return self.namespace_bq

    def bq_table(self, table: str) -> str:
        """Fully-qualified BQ table reference (dataset.table)."""
        return f"{self.bq_dataset}.{_bq_safe(table)}"

    def bq_feature_table(self, entity: str, feature_group: str) -> str:
        return f"{self.bq_dataset}.feat_{_bq_safe(entity)}_{_bq_safe(feature_group)}"

    # ── Vertex AI ─────────────────────────────────────────────────────────────

    def vertex_pipeline_display_name(self, pipeline_name: str) -> str:
        return f"{self.namespace}-{_slugify(pipeline_name)}"

    def vertex_experiment(self, pipeline_name: str) -> str:
        return f"{self.namespace}-{_slugify(pipeline_name)}-exp"

    def vertex_model_name(self, model_name: str) -> str:
        return f"{self.namespace}-{_slugify(model_name)}"

    def vertex_endpoint_name(self, model_name: str) -> str:
        return f"{self.namespace}-{_slugify(model_name)}-endpoint"

    def vertex_training_job_name(self, job_name: str) -> str:
        return f"{self.namespace}-{_slugify(job_name)}"

    # ── Artifact Registry ─────────────────────────────────────────────────────

    def artifact_registry_repo(self, registry_host: str, gcp_project: str) -> str:
        """Returns the AR repository path (shared per team+project, not per branch)."""
        return f"{registry_host}/{gcp_project}/{self.team}-{self.project}"

    def image_tag(self, image_name: str, sha: str | None = None) -> str:
        """Image tag: {branch_safe}-{sha} for traceability."""
        sha = sha or get_git_sha()
        return f"{self.branch}-{sha}"

    def image_uri(
        self,
        registry_host: str,
        gcp_project: str,
        image_name: str,
        sha: str | None = None,
    ) -> str:
        repo = self.artifact_registry_repo(registry_host, gcp_project)
        return f"{repo}/{_slugify(image_name)}:{self.image_tag(image_name, sha)}"

    # ── Feature Store ─────────────────────────────────────────────────────────

    @cached_property
    def feature_store_id(self) -> str:
        """One Vertex AI Feature Store per team+project (shared across branches)."""
        return f"{_bq_safe(self.team)}_{_bq_safe(self.project)}"

    def feature_view_id(self, entity: str, feature_group: str) -> str:
        """Feature view is branch-namespaced to prevent contamination."""
        return f"{_bq_safe(entity)}_{_bq_safe(feature_group)}_{_bq_safe(self.branch)}"

    # ── Cloud Composer / Airflow ──────────────────────────────────────────────

    def dag_id(self, pipeline_name: str) -> str:
        """Double-underscore separator for human readability."""
        return f"{self.namespace_bq}__{_bq_safe(pipeline_name)}"

    # ── Secret Manager ────────────────────────────────────────────────────────

    def secret_name(self, key: str) -> str:
        """Namespaced secret name: {namespace}-{key}."""
        return f"{self.namespace}-{_slugify(key)}"

    # ── Repr ──────────────────────────────────────────────────────────────────

    def resource_map(self, gcp_project: str) -> dict[str, str]:
        """Return a dict of all derived resource names for display / debugging."""
        return {
            "namespace": self.namespace,
            "gcs_bucket": self.gcs_bucket,
            "gcs_prefix": self.gcs_prefix,
            "bq_dataset": f"{gcp_project}.{self.bq_dataset}",
            "feature_store_id": self.feature_store_id,
            "dag_id_pattern": self.dag_id("{pipeline_name}"),
            "vertex_experiment_pattern": self.vertex_experiment("{pipeline_name}"),
        }
