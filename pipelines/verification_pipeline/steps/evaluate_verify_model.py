"""Evaluation step for verification pipeline — regression metrics on housing data."""

from gcp_ml_framework.components.ml.evaluate import EvaluateModel


class EvaluateVerifyStep(EvaluateModel):
    """Housing regression evaluation for the verification pipeline.

    Falls back to constructing the eval table reference from self.dataset
    if dataset_uri is not bridged from the @task group.
    """

    component_name: str = "evaluate_verify_model"

    def run(self) -> None:
        if not self.dataset_uri:
            self.dataset_uri = (
                f"{self.project}.{self.dataset}.verification_features"
            )
        super().run()


if __name__ == "__main__":
    EvaluateVerifyStep.cli()
