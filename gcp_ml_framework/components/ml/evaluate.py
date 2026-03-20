"""EvaluateModel — evaluate a trained model and apply metric gates."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig


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
    config: ComponentConfig = Field(default_factory=ComponentConfig)

    def execute(self) -> None:
        """Container lifecycle: delegate to utils.evaluate.run_evaluate()."""
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
