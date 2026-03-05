"""TrainModel — submit a Vertex AI Custom Training Job."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class TrainModel(BaseComponent):
    """
    Submit a Vertex AI Custom Training Job using a custom container.

    The training container receives:
        --model-output <gcs_path>   — where to write the model artifact
        --dataset-path <gcs_path>   — input dataset URI (from upstream component)

    Plus any additional `trainer_args` you specify.

    Example:
        TrainModel(
            trainer_image="us-central1-docker.pkg.dev/my-proj/trainers/churn:latest",
            machine_type="n2-standard-8",
            hyperparameters={"learning_rate": 0.01, "max_depth": 6},
        )
    """

    trainer_image: str = ""
    machine_type: str = "n2-standard-4"
    accelerator_type: str = ""
    accelerator_count: int = 0
    trainer_args: list[str] = field(default_factory=list)
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    component_name: str = "train_model"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def resolve_image_uri(
        self, pipeline_name: str, context: "MLContext", pipeline_dir: "Path | None" = None
    ) -> str:
        """Resolve the trainer image URI.

        If trainer_image is set, return it as-is.
        Otherwise, derive from the pipeline directory name (matching
        ``docker_build.sh`` convention) or fall back to pipeline_name.
        """
        if self.trainer_image:
            return self.trainer_image
        from gcp_ml_framework.naming import _slugify

        source_name = pipeline_dir.name if pipeline_dir else pipeline_name
        image_name = _slugify(source_name) + "-trainer"
        return context.naming.image_uri(
            registry_host=context.artifact_registry_host,
            gcp_project=context.gcp_project,
            image_name=image_name,
        )

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=["google-cloud-aiplatform>=1.49"],
        )
        def train_model(
            project: str,
            region: str,
            staging_bucket: str,
            experiment_name: str,
            job_name: str,
            trainer_image: str,
            machine_type: str,
            accelerator_type: str,
            accelerator_count: int,
            trainer_args: str,  # JSON list
            hyperparameters: str,  # JSON dict
            model_output_uri: str,
            run_id: str = "",
            dataset_uri: str = "",
        ) -> str:
            """Returns GCS URI of the saved model artifact."""
            import json

            from google.cloud import aiplatform

            aiplatform.init(
                project=project,
                location=region,
                staging_bucket=staging_bucket,
                experiment=experiment_name,
            )

            # Use versioned model output path if run_id is provided
            versioned_uri = model_output_uri
            if run_id:
                versioned_uri = f"{model_output_uri.rstrip('/')}/{run_id}"

            args = json.loads(trainer_args) + [f"--model-output={versioned_uri}"]
            if dataset_uri:
                args.append(f"--dataset-path={dataset_uri}")
            for k, v in json.loads(hyperparameters).items():
                args.append(f"--{k}={v}")

            worker_pool: dict = {
                "machine_spec": {"machine_type": machine_type},
                "replica_count": 1,
                "container_spec": {"image_uri": trainer_image, "args": args},
            }
            if accelerator_type and accelerator_count > 0:
                worker_pool["machine_spec"]["accelerator_type"] = accelerator_type
                worker_pool["machine_spec"]["accelerator_count"] = accelerator_count

            job = aiplatform.CustomJob(
                display_name=job_name,
                worker_pool_specs=[worker_pool],
                staging_bucket=staging_bucket,
            )
            job.run(sync=True, experiment=experiment_name)
            return model_output_uri

        return train_model

    def local_run(self, context: "MLContext", dataset_path: str = "", **kwargs: Any) -> str:
        """Simulate training locally — writes a placeholder model artifact."""
        import json
        import os
        import tempfile

        pipeline_name = kwargs.get("pipeline_name", "unnamed")
        run_id = kwargs.get("run_id", "local")

        print(f"[local] TrainModel: image={self.trainer_image!r}, machine={self.machine_type!r}")
        print(f"[local] TrainModel: hyperparameters={self.hyperparameters}")
        print(f"[local] TrainModel: pipeline={pipeline_name}, run_id={run_id}")

        # Use versioned output path: {pipeline_name}/{run_id}/
        base_dir = tempfile.mkdtemp(prefix="gml_model_")
        out_dir = os.path.join(base_dir, pipeline_name, run_id)
        os.makedirs(out_dir, exist_ok=True)

        # Write a placeholder model file
        model_path = os.path.join(out_dir, "model.json")
        with open(model_path, "w") as f:
            json.dump(
                {
                    "framework": "placeholder",
                    "hyperparameters": self.hyperparameters,
                    "pipeline_name": pipeline_name,
                    "run_id": run_id,
                },
                f,
            )
        return out_dir
