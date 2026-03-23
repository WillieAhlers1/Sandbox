"""TrainModel — train a model directly inside the pipeline container."""

import os
import tempfile
from pathlib import Path

from loguru import logger
from pydantic import PrivateAttr

from gcp_ml_framework.components.base import _INTERNAL_FIELDS, BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class TrainModel(BaseComponent):
    """
    Train a model directly inside the KFP pipeline container.

    component_name is the step file name under steps/.
    E.g. component_name="train_house_model" → steps/train_house_model.py

    Lifecycle (per REQS 1.0):
        execute() creates a temp dir as self._work_dir, calls self.run(),
        uploads everything in self._work_dir to GCS, and writes the output URI.
        Data scientists override run() only — pure business logic.
        They write model artifacts to self._work_dir and never touch GCS.

    Example:
        TrainModel(
            component_name="train_house_model",
            machine_type="n2-standard-8",
        )
    """

    # Component-specific fields
    model_output_uri: str = ""
    job_name: str = ""
    run_id: str = ""
    experiment_name: str = ""

    component_name: str = ""

    # Managed by execute() — data scientists write model artifacts here in run()
    _work_dir: Path = PrivateAttr(default=Path())

    def execute(self) -> None:
        """Container lifecycle: create temp dir, call run(), upload to GCS, write output URI."""
        from gcp_ml_framework.utils.gcs import upload_file

        # Create temp dir — data scientist writes model files to self._work_dir
        self._work_dir = Path(tempfile.mkdtemp())
        self.run()

        # Upload all files in _work_dir to GCS
        if self.model_output_uri:
            versioned_uri = self.model_output_uri
            if self.run_id:
                versioned_uri = f"{self.model_output_uri.rstrip('/')}/{self.run_id}"

            for root, _dirs, files in os.walk(self._work_dir):
                for fname in files:
                    local_path = Path(root) / fname
                    rel_path = local_path.relative_to(self._work_dir)
                    gcs_uri = f"{versioned_uri.rstrip('/')}/{rel_path}"
                    upload_file(local_path, gcs_uri, self.project)
                    logger.info(f"Uploaded {rel_path} → {gcs_uri}")

        # Write output URI (create parent dirs — KFP FUSE mounts don't pre-exist)
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_uri_path, "w") as f:
                f.write(self.model_output_uri)

        # Experiment tracking (best-effort — never fail the pipeline)
        if self.experiment_name and self.project and self.region:
            try:
                from google.cloud import aiplatform

                aiplatform.init(
                    project=self.project,
                    location=self.region,
                    experiment=self.experiment_name,
                )
                run_id = f"train-{self.run_date or 'no-date'}"
                aiplatform.start_run(run=run_id, resume=True)
                params = {
                    k: str(v)
                    for k, v in self.model_dump().items()
                    if k not in _INTERNAL_FIELDS
                    and k != "output_uri_path"
                    and v not in ("", None, [], {})
                }
                aiplatform.log_params(params)
                logger.info(
                    "Logged training params to experiment: %s",
                    self.experiment_name,
                )
            except Exception:
                logger.warning("Experiment tracking failed (non-fatal)", exc_info=True)

    def run(self) -> None:
        """Business logic: train model, write artifacts to self._work_dir.

        Override this method with your training code. Write model files
        (e.g. model.pkl) to self._work_dir. The base execute() creates the
        temp directory and handles GCS upload and output URI writing.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() is not implemented. "
            "Override this method in your step subclass."
        )


if __name__ == "__main__":
    TrainModel.cli()
