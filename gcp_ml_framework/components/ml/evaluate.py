"""EvaluateModel — evaluate a trained model and apply metric gates."""

import json
from pathlib import Path

from loguru import logger
from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class EvaluateModel(BaseComponent):
    """
    Evaluate a model against a held-out dataset and apply metric gates.

    If any gate threshold is not met, the component raises an exception which
    halts the KFP pipeline (preventing deployment of a poor model).

    Example:
        EvaluateModel(
            component_name="evaluate",
            metrics=["auc", "f1"],
            gate={"auc": 0.75},
        )
    """

    # Component-specific fields
    dataset_uri: str = ""
    model_uri: str = ""
    experiment_name: str = ""

    metrics: list[str] = Field(default_factory=lambda: ["auc"])
    gate: dict[str, float] = Field(default_factory=dict)
    component_name: str = "evaluate_model"

    def execute(self) -> None:
        """Container lifecycle: call run(), then log metrics to experiments."""
        self.run()

        # Experiment tracking (best-effort) — resume the same run as TrainModel
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

                if self.output_uri_path and Path(self.output_uri_path).exists():
                    metrics = json.loads(Path(self.output_uri_path).read_text())
                    aiplatform.log_metrics(metrics)
                    logger.info(
                        "Logged eval metrics to experiment: %s",
                        self.experiment_name,
                    )
            except Exception:
                logger.warning(
                    "Experiment metric logging failed (non-fatal)",
                    exc_info=True,
                )

    def run(self) -> None:
        """Evaluate model against dataset. Override for custom evaluation logic."""
        from gcp_ml_framework.utils.evaluate import run_evaluate

        run_evaluate(
            project=self.project,
            region=self.region,
            model_uri=self.model_uri,
            eval_dataset_uri=self.dataset_uri,
            metrics=self.metrics,
            gate=self.gate,
            experiment_name=self.experiment_name,
            output_uri_path=self.output_uri_path,
        )



if __name__ == "__main__":
    EvaluateModel.cli()
