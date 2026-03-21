"""Tests for gcp_ml_framework.naming — _slugify, _bq_safe, NamingConvention."""

from __future__ import annotations

import pytest

from gcp_ml_framework.naming import NamingConvention, _bq_safe, _slugify

pytestmark = pytest.mark.unit


# ── _slugify ────────────────────────────────────────────────────────────────


class TestSlugify:
    def test_slugify_basic(self) -> None:
        """Simple case: spaces become hyphens, lowercase."""
        assert _slugify("Hello World") == "hello-world"

    def test_slugify_special_chars(self) -> None:
        """Slashes, underscores, mixed chars all become single hyphens."""
        assert _slugify("feature/my-branch_v2") == "feature-my-branch-v2"

    def test_slugify_truncation(self) -> None:
        """Output is truncated to max_len."""
        long = "a" * 50
        result = _slugify(long, max_len=10)
        assert len(result) == 10
        assert result == "aaaaaaaaaa"


# ── _bq_safe ────────────────────────────────────────────────────────────────


class TestBQSafe:
    def test_bq_safe_basic(self) -> None:
        """Hyphens become underscores."""
        assert _bq_safe("hello-world") == "hello_world"

    def test_bq_safe_special_chars(self) -> None:
        """Non-alphanumeric characters (except underscore) become underscores."""
        assert _bq_safe("feature/my-branch") == "feature_my_branch"


# ── NamingConvention.__init__ ───────────────────────────────────────────────


class TestNamingAutoSlugify:
    def test_naming_auto_slugifies(self) -> None:
        """team, project, and branch are automatically slugified on init."""
        nc = NamingConvention(
            team="My Team", project="My Project!", branch="feature/ABC_123",
        )
        assert nc.team == "my-team"
        assert nc.project == "my-project"
        assert nc.branch == "feature-abc-123"


# ── Namespace ───────────────────────────────────────────────────────────────


class TestNamespace:
    def test_namespace(self, mock_naming: NamingConvention) -> None:
        """namespace is {team}-{project}-{branch}."""
        expected = f"{mock_naming.team}-{mock_naming.project}-{mock_naming.branch}"
        assert mock_naming.namespace == expected

    def test_namespace_bq(self, mock_naming: NamingConvention) -> None:
        """namespace_bq is the underscore-safe version of namespace."""
        assert "_" not in mock_naming.namespace  # sanity: the slug has no underscores
        expected = _bq_safe(mock_naming.namespace)
        assert mock_naming.namespace_bq == expected


# ── GCS ─────────────────────────────────────────────────────────────────────


class TestGCS:
    def test_gcs_bucket_with_project(self) -> None:
        """When gcp_project is set, bucket is {gcp_project}-{team}-{project}."""
        nc = NamingConvention(
            team="teamx", project="projy", branch="main", gcp_project="my-gcp",
        )
        assert nc.gcs_bucket == "my-gcp-teamx-projy"

    def test_gcs_bucket_without_project(self) -> None:
        """When gcp_project is None, bucket is {team}-{project}."""
        nc = NamingConvention(team="teamx", project="projy", branch="main")
        assert nc.gcs_bucket == "teamx-projy"

    def test_gcs_prefix(self, mock_naming: NamingConvention) -> None:
        """gcs_prefix is gs://{bucket}/{branch}/"""
        expected = f"gs://{mock_naming.gcs_bucket}/{mock_naming.branch}/"
        assert mock_naming.gcs_prefix == expected

    def test_gcs_path(self, mock_naming: NamingConvention) -> None:
        """gcs_path joins parts under gcs_prefix."""
        result = mock_naming.gcs_path("data", "raw", "file.csv")
        assert result == mock_naming.gcs_prefix + "data/raw/file.csv"


# ── BigQuery ────────────────────────────────────────────────────────────────


class TestBigQuery:
    def test_bq_dataset(self, mock_naming: NamingConvention) -> None:
        """bq_dataset equals namespace_bq."""
        assert mock_naming.bq_dataset == mock_naming.namespace_bq

    def test_bq_table(self, mock_naming: NamingConvention) -> None:
        """bq_table returns {dataset}.{bq_safe_table}."""
        result = mock_naming.bq_table("my-table")
        assert result == f"{mock_naming.bq_dataset}.{_bq_safe('my-table')}"


# ── Vertex AI ───────────────────────────────────────────────────────────────


class TestVertexAI:
    def test_vertex_experiment(self, mock_naming: NamingConvention) -> None:
        """vertex_experiment is {namespace}-{slugified_pipeline}-exp."""
        result = mock_naming.vertex_experiment("train_model")
        expected = f"{mock_naming.namespace}-{_slugify('train_model')}-exp"
        assert result == expected

    def test_vertex_model_name(self, mock_naming: NamingConvention) -> None:
        """vertex_model_name is {namespace}-{slugified_model}."""
        result = mock_naming.vertex_model_name("churn-predictor")
        expected = f"{mock_naming.namespace}-{_slugify('churn-predictor')}"
        assert result == expected


# ── Composer / Airflow ──────────────────────────────────────────────────────


class TestComposer:
    def test_dag_id(self, mock_naming: NamingConvention) -> None:
        """dag_id is {namespace_bq}__{bq_safe_pipeline}."""
        result = mock_naming.dag_id("training-pipeline")
        expected = f"{mock_naming.namespace_bq}__{_bq_safe('training-pipeline')}"
        assert result == expected


# ── Feature Store ───────────────────────────────────────────────────────────


class TestFeatureStore:
    def test_feature_store_id(self, mock_naming: NamingConvention) -> None:
        """feature_store_id is {bq_safe_team}_{bq_safe_project}."""
        expected = f"{_bq_safe(mock_naming.team)}_{_bq_safe(mock_naming.project)}"
        assert mock_naming.feature_store_id == expected

    def test_feature_view_id(self, mock_naming: NamingConvention) -> None:
        """feature_view_id is {entity}_{group}_{branch} (all bq_safe)."""
        result = mock_naming.feature_view_id("customer", "demographics")
        expected = (
            f"{_bq_safe('customer')}_{_bq_safe('demographics')}"
            f"_{_bq_safe(mock_naming.branch)}"
        )
        assert result == expected
