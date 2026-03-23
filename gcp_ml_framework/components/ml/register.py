"""RegisterModel — upload a model to the Vertex AI Model Registry."""

from pathlib import Path

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class RegisterModel(BaseComponent):
    """Upload a trained model to Vertex AI Model Registry.

    This component has two Docker-related fields with distinct purposes:

    - ``runtime_dockerfile`` (inherited from ``BaseComponent``): the Docker image
      this component **executes in**. Every component must explicitly declare this.
    - ``serving_dockerfile``: the Docker image registered as the **serving
      container** in Vertex AI Model Registry — the image Vertex AI uses when
      the model is deployed to an endpoint.

    The serving container image is resolved using a three-tier priority:

    1. ``serving_container_image`` (full URI) — used as-is. Use this for
       external or pre-built images (e.g. Google's CPR base images).

       .. code-block:: python

           RegisterModel(
               serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest"
           )

    2. ``serving_dockerfile`` (path relative to ``docker/``) — resolved at
       compile time by the ``PipelineCompiler`` into a full Artifact Registry
       URI via ``NamingConvention.docker_image_uri()``.

       .. code-block:: python

           RegisterModel(serving_dockerfile="pipelines/house_price/regression_serve.Dockerfile")

    3. Neither set — the compiler falls back to the pipeline's default training
       image (``docker/train.Dockerfile``). This is the right default for batch
       prediction where the serving runtime matches the training runtime.

       .. code-block:: python

           RegisterModel()

    See ``docs/docker_discussion.md`` and ``docs/register.md`` for the full
    design rationale.

    Args:
        model_uri: GCS path to the trained model artifacts.
        model_name: Short identifier for the model (e.g. ``"regression"``,
            ``"classifier"``). Appended to the derived display name so that
            a single pipeline can register multiple models without collision.
            When not set, the display name is derived from the pipeline name
            alone (backwards-compatible).
        model_display_name: Display name in Model Registry. Auto-derived from
            pipeline name (+ model_name) by the compiler when not set.
        serving_container_image: Full URI of the serving container. Takes
            priority over ``serving_dockerfile``.
        serving_dockerfile: Path to the serving Dockerfile relative to
            ``docker/`` (e.g. ``"pipelines/house_price/regression_serve.Dockerfile"``).
            Resolved to a full AR URI by the compiler.
        labels: Key-value labels attached to the registered model.
        description: Human-readable description of the model version.
    """

    model_uri: str = ""
    model_name: str = ""
    model_display_name: str = ""
    serving_dockerfile: str = ""
    serving_container_image: str = ""
    labels: dict[str, str] = Field(default_factory=dict)
    description: str = ""
    component_name: str = "register_model"

    def execute(self) -> None:
        """Container lifecycle: call run(), write output URI."""
        resource_name = self.run()
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(resource_name)

    def run(self) -> str:
        """Register model in Vertex AI Model Registry. Override for custom registration.

        If a model with the same display name already exists, a new version is
        created under that parent model. Otherwise, a new parent model (v1) is
        created. See ``docs/register.md`` for design rationale.

        Returns:
            The registered model's resource name.
        """
        from google.cloud import aiplatform
        from loguru import logger

        aiplatform.init(project=self.project, location=self.region)

        # Look up existing model to create a new version instead of a new artifact
        parent_model = None
        existing = aiplatform.Model.list(
            filter=f'display_name="{self.model_display_name}"',
            project=self.project,
            location=self.region,
        )
        if existing:
            parent_model = existing[0].resource_name
            logger.info(
                f"Found existing model '{self.model_display_name}' — "
                f"creating new version under {parent_model}"
            )
        else:
            logger.info(f"No existing model '{self.model_display_name}' — creating v1")

        upload_kwargs: dict = {
            "display_name": self.model_display_name,
            "artifact_uri": self.model_uri,
            "serving_container_image_uri": self.serving_container_image,
            "labels": self.labels,
            "description": self.description,
            "sync": False,
        }
        if parent_model:
            upload_kwargs["parent_model"] = parent_model
            upload_kwargs["is_default_version"] = True

        model = aiplatform.Model.upload(**upload_kwargs)
        logger.info(f"Registered model: {model.resource_name}")
        return str(model.resource_name)


if __name__ == "__main__":
    RegisterModel.cli()
