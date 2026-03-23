"""WriteFeatures — Feature Store integration component."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from pathlib import Path

    from gcp_ml_framework.context import MLContext


@task
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

    def render_operator(
        self,
        context: MLContext,
        pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation.

        WriteFeatures is a metadata-only GCP SDK call with no native Airflow
        operator, so we render as a PythonOperator stub. The actual Feature Store
        registration happens via the Vertex AI SDK at runtime.
        """
        imports = {"from airflow.operators.python import PythonOperator"}

        func_name = f"_write_features_{self.feature_group_id or self.component_name}"
        code = f"""def {func_name}(**kwargs):
        pass  # WriteFeatures is metadata-only; no runtime action in DAG

    PythonOperator(
        task_id="{{{{ task_id }}}}",
        python_callable={func_name},
    )"""

        return code, imports


if __name__ == "__main__":
    WriteFeatures.cli()
