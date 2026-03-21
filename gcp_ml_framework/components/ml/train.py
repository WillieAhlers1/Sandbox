"""TrainModel — train a model directly inside the pipeline container."""

import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, PrivateAttr

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

    # Private attr for execute() to pass work dir to run()
    _work_dir: str = PrivateAttr(default="")

    trainer_args: list[str] = Field(default_factory=list)
    hyperparameters: dict[str, Any] = Field(default_factory=dict)
    component_name: str = ""

    def execute(self) -> None:
        """Container lifecycle: create temp dir, call run(), upload to GCS, write output URI."""
        from gcp_ml_framework.utils.gcs import upload_file

        with tempfile.TemporaryDirectory(prefix="gml_train_") as temp_dir:
            # Set _work_dir so run() can access it via self._work_dir
            self._work_dir = temp_dir

            # Call run() — data scientist writes model files to self._work_dir
            self.run()

            # Upload all files in temp_dir to GCS
            if self.model_output_uri:
                versioned_uri = self.model_output_uri
                if self.run_id:
                    versioned_uri = f"{self.model_output_uri.rstrip('/')}/{self.run_id}"

                for root, _dirs, files in os.walk(temp_dir):
                    for fname in files:
                        local_path = Path(root) / fname
                        rel_path = local_path.relative_to(temp_dir)
                        gcs_uri = f"{versioned_uri.rstrip('/')}/{rel_path}"
                        upload_file(local_path, gcs_uri, self.project)
                        logger.info(f"Uploaded {rel_path} → {gcs_uri}")

            # Write output URI (create parent dirs — KFP FUSE mounts don't pre-exist)
            if self.output_uri_path:
                Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self.output_uri_path, "w") as f:
                    f.write(self.model_output_uri)



if __name__ == "__main__":
    TrainModel.cli()
