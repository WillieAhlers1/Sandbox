"""WriteFeatures / ReadFeatures — Feature Store integration components."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig


class WriteFeatures(BaseComponent):
    """
    Register a BQ table as a Vertex AI Feature Store v2 FeatureGroup.

    This is a metadata-only operation — no data movement.

    Example:
        WriteFeatures(
            component_name="write_features",
            entity="user",
            feature_group="churn_signals",
            entity_id_column="user_id",
        )
    """

    # Component-specific fields
    feature_group_id: str = ""

    entity: str
    feature_group: str
    entity_id_column: str = "entity_id"
    feature_time_column: str = "feature_timestamp"
    feature_ids: list[str] = Field(default_factory=list)
    bq_source_table: str | None = None
    component_name: str = "write_features"
    config: ComponentConfig = Field(default_factory=ComponentConfig)

    def execute(self) -> None:
        """Container lifecycle: delegate to utils.feature_store.run_write_features()."""
        from gcp_ml_framework.utils.feature_store import run_write_features

        run_write_features(
            project=self.project,
            region=self.region,
            feature_group_id=self.feature_group_id,
            bq_source_table=self.bq_source_table or "",
            entity_id_column=self.entity_id_column,
            output_uri_path=self.output_uri_path,
        )



class ReadFeatures(BaseComponent):
    """
    Read feature values from the Vertex AI Feature Store for training or serving.

    For training: reads from the BQ source table (offline, point-in-time safe).
    For serving:  reads from the Bigtable online store (low-latency).
    """

    entity: str
    feature_group: str
    feature_ids: list[str] = Field(default_factory=list)
    output_table: str = "features_read"
    component_name: str = "read_features"
    config: ComponentConfig = Field(default_factory=ComponentConfig)



if __name__ == "__main__":
    # Default to WriteFeatures; ReadFeatures can be invoked via its own module
    WriteFeatures.cli()
