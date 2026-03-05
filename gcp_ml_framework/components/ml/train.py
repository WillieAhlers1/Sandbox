"""TrainModel — submit a Vertex AI Custom Training Job."""

from dataclasses import dataclass, field
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

    trainer_image: str
    machine_type: str = "n2-standard-4"
    accelerator_type: str = ""
    accelerator_count: int = 0
    trainer_args: list[str] = field(default_factory=list)
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    component_name: str = "train_model"
    config: ComponentConfig = field(default_factory=ComponentConfig)

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
            dataset_uri: str = "",
        ) -> str:
            """Returns GCS URI of the saved model artifact."""
            import json

            from google.cloud import aiplatform

            aiplatform.init(
                project=project, location=region,
                staging_bucket=staging_bucket,
                experiment=experiment_name,
            )

            args = json.loads(trainer_args) + [f"--model-output={model_output_uri}"]
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

        print(f"[local] TrainModel: image={self.trainer_image!r}, machine={self.machine_type!r}")
        print(f"[local] TrainModel: hyperparameters={self.hyperparameters}")
        out_dir = tempfile.mkdtemp(prefix="gml_model_")
        # Write a placeholder model file
        model_path = os.path.join(out_dir, "model.json")
        with open(model_path, "w") as f:
            json.dump({"framework": "placeholder", "hyperparameters": self.hyperparameters}, f)
        return out_dir
