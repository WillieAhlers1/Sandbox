"""
Feature Store entity and feature schema definitions.

Schemas are defined in YAML files (feature_schemas/{entity}.yaml) and parsed
into EntitySchema/FeatureGroupSchema dataclasses for use by the FeatureStoreClient
and gml deploy features command.

YAML format:
    entity: user
    id_column: user_id
    id_type: STRING
    feature_groups:
      behavioral:
        description: "Engagement signals"
        features:
          - name: session_count_7d
            type: INT64
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import yaml


class FeatureType(StrEnum):
    INT64 = "INT64"
    FLOAT64 = "FLOAT64"
    STRING = "STRING"
    BOOL = "BOOL"
    BYTES = "BYTES"
    DOUBLE = "DOUBLE"
    DOUBLE_ARRAY = "DOUBLE_ARRAY"
    INT64_ARRAY = "INT64_ARRAY"
    STRING_ARRAY = "STRING_ARRAY"


@dataclass
class FeatureDef:
    name: str
    type: FeatureType
    description: str = ""


@dataclass
class FeatureGroupSchema:
    name: str
    description: str
    features: list[FeatureDef] = field(default_factory=list)


@dataclass
class EntitySchema:
    """
    Describes a Vertex AI Feature Store entity type and all its feature groups.

    An entity corresponds to a business object (User, Item, Session…).
    Feature groups partition features by domain (behavioral, demographic, etc.).
    """

    entity: str          # Entity type ID, e.g. "user"
    id_column: str       # Source table column used as the entity ID
    id_type: FeatureType = FeatureType.STRING
    description: str = ""
    feature_groups: dict[str, FeatureGroupSchema] = field(default_factory=dict)

    def all_features(self) -> list[FeatureDef]:
        return [f for g in self.feature_groups.values() for f in g.features]

    def feature_names(self) -> list[str]:
        return [f.name for f in self.all_features()]


def _parse_entity_schema(data: dict) -> EntitySchema:
    feature_groups: dict[str, FeatureGroupSchema] = {}
    for group_name, group_data in data.get("feature_groups", {}).items():
        features = [
            FeatureDef(
                name=f["name"],
                type=FeatureType(f["type"]),
                description=f.get("description", ""),
            )
            for f in group_data.get("features", [])
        ]
        feature_groups[group_name] = FeatureGroupSchema(
            name=group_name,
            description=group_data.get("description", ""),
            features=features,
        )
    return EntitySchema(
        entity=data["entity"],
        id_column=data["id_column"],
        id_type=FeatureType(data.get("id_type", "STRING")),
        description=data.get("description", ""),
        feature_groups=feature_groups,
    )


def load_entity_schemas(schema_dir: Path | str = "feature_schemas") -> dict[str, EntitySchema]:
    """
    Load all entity schemas from YAML files in schema_dir.

    Returns a dict of {entity_name: EntitySchema}.
    """
    schema_dir = Path(schema_dir)
    schemas: dict[str, EntitySchema] = {}
    for yaml_file in sorted(schema_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        schema = _parse_entity_schema(data)
        schemas[schema.entity] = schema
    return schemas


def load_entity_schema(yaml_path: Path | str) -> EntitySchema:
    """Load a single entity schema from a YAML file."""
    data = yaml.safe_load(Path(yaml_path).read_text())
    return _parse_entity_schema(data)
