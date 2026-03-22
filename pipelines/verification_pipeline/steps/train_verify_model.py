"""Simple training step for verification — trains on verification_features table."""

import pickle
from pathlib import Path

from loguru import logger

from gcp_ml_framework.components.ml.train import TrainModel


class TrainVerifyModelStep(TrainModel):
    """Minimal training step for architecture verification."""

    def run(self) -> None:
        from google.cloud import bigquery

        from second_run.estimator import HousePredictionModel

        logger.info(
            f"[train_verify_model] project={self.project}, "
            f"dataset={self.dataset}"
        )
        client = bigquery.Client(project=self.project)
        query = f"SELECT * FROM `{self.dataset}.verification_features`"
        df = client.query(query).to_dataframe()

        model = HousePredictionModel()
        model.fit(df, df["price"])

        local_path = Path(self._work_dir) / "model.pkl"
        with open(local_path, "wb") as f:
            pickle.dump(model, f)
        logger.info(f"[train_verify_model] Model saved to {local_path}")


if __name__ == "__main__":
    TrainVerifyModelStep.cli()
