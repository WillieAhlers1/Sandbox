"""Unit tests for naming.py — namespace resolution and sanitization."""

import pytest

from gcp_ml_framework.naming import NamingConvention, _bq_safe, _slugify


class TestSlugify:
    def test_basic(self):
        assert _slugify("hello-world") == "hello-world"

    def test_slash_becomes_hyphen(self):
        assert _slugify("feature/user-embeddings") == "feature-user-embeddings"

    def test_uppercase_lowercased(self):
        assert _slugify("MyProject") == "myproject"

    def test_special_chars_removed(self):
        assert _slugify("hello@world!") == "hello-world"

    def test_max_len(self):
        result = _slugify("a" * 50, max_len=20)
        assert len(result) == 20

    def test_leading_trailing_hyphens_stripped(self):
        assert not _slugify("--hello--").startswith("-")
        assert not _slugify("--hello--").endswith("-")


class TestBqSafe:
    def test_hyphens_become_underscores(self):
        assert _bq_safe("feature-branch") == "feature_branch"

    def test_slash_becomes_underscore(self):
        assert _bq_safe("feature/xyz") == "feature_xyz"


class TestNamingConvention:
    def test_namespace(self, naming_dev):
        assert naming_dev.namespace == "dsci-churn-pred-feature-user-embeddings"

    def test_namespace_main(self, naming_main):
        assert naming_main.namespace == "dsci-churn-pred-main"

    def test_bq_dataset_no_hyphens(self, naming_dev):
        assert "-" not in naming_dev.bq_dataset

    def test_bq_dataset_underscores(self, naming_dev):
        assert "_" in naming_dev.bq_dataset

    def test_gcs_bucket_shared(self, naming_dev, naming_main):
        """Branches share the same GCS bucket (different prefixes)."""
        assert naming_dev.gcs_bucket == naming_main.gcs_bucket

    def test_gcs_prefix_includes_branch(self, naming_dev):
        assert "feature" in naming_dev.gcs_prefix

    def test_gcs_prefix_ends_with_slash(self, naming_dev):
        assert naming_dev.gcs_prefix.endswith("/")

    def test_dag_id_format(self, naming_dev):
        dag_id = naming_dev.dag_id("churn_train")
        assert "__" in dag_id
        assert "-" not in dag_id  # BQ-safe

    def test_vertex_endpoint_name(self, naming_main):
        name = naming_main.vertex_endpoint_name("churn-v1")
        assert "dsci-churn-pred-main" in name
        assert "endpoint" in name

    def test_feature_view_encodes_branch(self, naming_dev):
        view_id = naming_dev.feature_view_id("user", "behavioral")
        assert "feature" in view_id  # branch slug

    def test_feature_store_id_shared(self, naming_dev, naming_main):
        """Feature store is shared per team+project, not per branch."""
        assert naming_dev.feature_store_id == naming_main.feature_store_id

    def test_secret_name(self, naming_main):
        name = naming_main.secret_name("db-password")
        assert name == "dsci-churn-pred-main-db-password"

    def test_team_truncated(self):
        nc = NamingConvention(team="a" * 20, project="proj", branch="main")
        assert len(nc.team) <= 12

    def test_frozen(self, naming_dev):
        with pytest.raises((AttributeError, TypeError)):
            naming_dev.team = "other"  # type: ignore[misc]

    def test_resource_map_keys(self, naming_main):
        rmap = naming_main.resource_map("my-project")
        assert "namespace" in rmap
        assert "gcs_prefix" in rmap
        assert "bq_dataset" in rmap

    # -- GCS bucket with gcp_project (Phase 1A) --

    def test_gcs_bucket_without_project_id_unchanged(self):
        """Without gcp_project, gcs_bucket is {team}-{project} (backwards compat)."""
        nc = NamingConvention(team="dsci", project="gcpdemo", branch="test")
        assert nc.gcs_bucket == "dsci-gcpdemo"

    def test_gcs_bucket_with_project_id(self):
        """With gcp_project, gcs_bucket is {project_id}-{team}-{project} (GCP best practice)."""
        nc = NamingConvention(
            team="dsci", project="gcpdemo", branch="test",
            gcp_project="prj-0n-dta-pt-ai-sandbox",
        )
        assert nc.gcs_bucket == "prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo"

    def test_gcs_prefix_with_project_id(self):
        """GCS prefix uses project-scoped bucket name."""
        nc = NamingConvention(
            team="dsci", project="gcpdemo", branch="feature/xyz",
            gcp_project="my-project",
        )
        assert nc.gcs_prefix == "gs://my-project-dsci-gcpdemo/feature-xyz/"

    def test_gcs_bucket_with_project_id_shared_across_branches(self):
        """Different branches share the same bucket even with gcp_project."""
        nc_dev = NamingConvention(
            team="dsci", project="gcpdemo", branch="feature/abc",
            gcp_project="my-project",
        )
        nc_main = NamingConvention(
            team="dsci", project="gcpdemo", branch="main",
            gcp_project="my-project",
        )
        assert nc_dev.gcs_bucket == nc_main.gcs_bucket

    def test_gcs_pipeline_root_with_project_id(self):
        """Pipeline root uses project-scoped bucket."""
        nc = NamingConvention(
            team="dsci", project="gcpdemo", branch="test",
            gcp_project="my-project",
        )
        root = nc.gcs_pipeline_root("churn_prediction")
        assert root.startswith("gs://my-project-dsci-gcpdemo/test/")
