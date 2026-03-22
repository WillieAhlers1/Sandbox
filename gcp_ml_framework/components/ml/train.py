"""TrainModel — train a model directly inside the pipeline container."""

import os
from pathlib import Path

from loguru import logger

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class TrainModel(BaseComponent):
    """
    Train a model directly inside the KFP pipeline container.

    component_name is the step file name under steps/.
    E.g. component_name="train_house_model" → steps/train_house_model.py

    Example:
        TrainModel(
            component_name="train_house_model",
            machine_type="n2-standard-8",
            hyperparameters={"learning_rate": 0.01, "max_depth": 6},
        )
    """

    # Component-specific fields
    model_output_uri: str = ""
    job_name: str = ""
    run_id: str = ""


    component_name: str = ""

    def execute(self) -> None:
        """Container lifecycle: create temp dir, call run(), upload to GCS, write output URI."""
        from gcp_ml_framework.utils.gcs import upload_file

        # Call run() — data scientist writes model files to self._work_dir
        artifact_location = self.run()

        # Upload all files in temp_dir to GCS
        if self.model_output_uri:
            versioned_uri = self.model_output_uri
            if self.run_id:
                versioned_uri = f"{self.model_output_uri.rstrip('/')}/{self.run_id}"

            for root, _dirs, files in os.walk(artifact_location):
                for fname in files:
                    local_path = Path(root) / fname
                    rel_path = local_path.relative_to(artifact_location)
                    gcs_uri = f"{versioned_uri.rstrip('/')}/{rel_path}"
                    upload_file(local_path, gcs_uri, self.project)
                    logger.info(f"Uploaded {rel_path} → {gcs_uri}")

        # Write output URI (create parent dirs — KFP FUSE mounts don't pre-exist)
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_uri_path, "w") as f:
                f.write(self.model_output_uri)

    def run(self) -> Path:
        """Business logic: train model, write to temp dir, return artifact location.

        Override this method with your training code. Write model files to self._work_dir.
        Return the local path to the trained model artifact (e.g. a directory or .tar.gz file).
        The base execute() implementation will handle GCS upload and output URI writing.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() is not implemented. "
            "Override this method in your step subclass."
        )




if __name__ == "__main__":
    TrainModel.cli()
