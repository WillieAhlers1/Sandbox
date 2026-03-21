"""Train the house price prediction model.

Step subclass convention: subclass a component and override run() with business logic.
The component's execute() handles I/O lifecycle (temp dirs, GCS upload, output URIs).
"""

import pickle
from pathlib import Path

from loguru import logger

from gcp_ml_framework.components.ml.train import TrainModel


class HouseTrainModelStep(TrainModel):
    """Train a house price prediction model."""

    def run(self) -> None:
        """Train the house price model and save to self._work_dir.

        TrainModel.execute() handles GCS upload of everything in _work_dir.
        """
        from importlib.resources import files

        from google.cloud import bigquery

        from second_run.estimator import HousePredictionModel

        logger.info(f"[train_house_model] project={self.project}")

        # Read training data from BigQuery
        logger.info("[train_house_model] Reading training data from BigQuery...")
        client = bigquery.Client(project=self.project)
        query_template = (
            files("pipelines.training_pipeline.sql")
            .joinpath("training_pipeline_features.sql")
            .read_text()
        )
        query = query_template.format(dataset=self.dataset)
        df = client.query(query).to_dataframe()

        # Train model
        logger.info("[train_house_model] Training model...")
        model = HousePredictionModel()
        model.fit(df, df["price"])

        # Save model to _work_dir — TrainModel.execute() uploads to GCS
        local_path = Path(self._work_dir) / "model.pkl"
        with open(local_path, "wb") as f:
            pickle.dump(model, f)
        logger.info(f"[train_house_model] Model saved to {local_path}")


if __name__ == "__main__":
    HouseTrainModelStep.cli()
