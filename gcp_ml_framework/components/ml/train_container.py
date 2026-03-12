"""TrainModel — container component variant (no inline code in compiled YAML).

This is a drop-in replacement for TrainModel.as_kfp_component(). Instead of
embedding ~80 lines of Python into the compiled YAML, it references the
component-base image and calls the CLI entrypoint.

PROTOTYPE — shows the pattern for converting all components.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig
from gcp_ml_framework.components.ml.train import TrainModel as _OriginalTrainModel

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class TrainModel(_OriginalTrainModel):
    """TrainModel using @dsl.container_component — no source code in YAML."""

    def as_kfp_component(self, base_image: str | None = None):
        from kfp import dsl

        image = base_image or "python:3.11-slim"

        @dsl.container_component
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
            trainer_args: str,
            hyperparameters: str,
            model_output_uri: str,
            run_id: str = "",
            dataset_uri: str = "",
            output_uri: dsl.OutputPath(str) = None,
        ):
            return dsl.ContainerSpec(
                image=image,
                command=["python", "-m", "gcp_ml_framework.components.ml.train_entrypoint"],
                args=[
                    "--project", project,
                    "--region", region,
                    "--staging-bucket", staging_bucket,
                    "--experiment-name", experiment_name,
                    "--job-name", job_name,
                    "--trainer-image", trainer_image,
                    "--machine-type", machine_type,
                    "--accelerator-type", accelerator_type,
                    "--accelerator-count", accelerator_count,
                    "--trainer-args", trainer_args,
                    "--hyperparameters", hyperparameters,
                    "--model-output-uri", model_output_uri,
                    "--run-id", run_id,
                    "--dataset-uri", dataset_uri,
                    "--output-uri-path", output_uri,
                ],
            )

        return train_model
