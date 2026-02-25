"""Unit tests for feature_store/schema.py — YAML parsing and validation."""

import textwrap
from pathlib import Path

import pytest
import yaml

from gcp_ml_framework.feature_store.schema import (
    EntitySchema,
    FeatureType,
    _parse_entity_schema,
    load_entity_schema,
    load_entity_schemas,
)

SAMPLE_YAML = textwrap.dedent("""\
    entity: user
    id_column: user_id
    id_type: STRING
    description: "Test user entity"
    feature_groups:
      behavioral:
        description: "Behavioral features"
        features:
          - name: session_count_7d
            type: INT64
          - name: avg_session_s
            type: FLOAT64
      demographic:
        description: "Demographics"
        features:
          - name: country
            type: STRING
""")


@pytest.fixture
def sample_schema() -> EntitySchema:
    return _parse_entity_schema(yaml.safe_load(SAMPLE_YAML))


@pytest.fixture
def schema_dir(tmp_path) -> Path:
    (tmp_path / "user.yaml").write_text(SAMPLE_YAML)
    return tmp_path


class TestEntitySchema:
    def test_entity_id(self, sample_schema):
        assert sample_schema.entity == "user"

    def test_id_column(self, sample_schema):
        assert sample_schema.id_column == "user_id"

    def test_id_type(self, sample_schema):
        assert sample_schema.id_type == FeatureType.STRING

    def test_feature_groups_count(self, sample_schema):
        assert len(sample_schema.feature_groups) == 2

    def test_all_features_count(self, sample_schema):
        assert len(sample_schema.all_features()) == 3

    def test_feature_names(self, sample_schema):
        names = sample_schema.feature_names()
        assert "session_count_7d" in names
        assert "country" in names

    def test_feature_types(self, sample_schema):
        behavioral = sample_schema.feature_groups["behavioral"]
        types = {f.name: f.type for f in behavioral.features}
        assert types["session_count_7d"] == FeatureType.INT64
        assert types["avg_session_s"] == FeatureType.FLOAT64


class TestLoadSchemas:
    def test_load_from_dir(self, schema_dir):
        schemas = load_entity_schemas(schema_dir)
        assert "user" in schemas
        assert isinstance(schemas["user"], EntitySchema)

    def test_load_from_file(self, schema_dir):
        schema = load_entity_schema(schema_dir / "user.yaml")
        assert schema.entity == "user"

    def test_load_project_schemas(self):
        """Load the actual project feature schemas (user.yaml, item.yaml)."""
        schemas = load_entity_schemas(Path("feature_schemas"))
        assert "user" in schemas
        assert "item" in schemas
        assert len(schemas["user"].all_features()) > 0
