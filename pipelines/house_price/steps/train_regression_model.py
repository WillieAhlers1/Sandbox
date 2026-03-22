"""Train the house price prediction model.

Step subclass convention: subclass a component and override run() with business logic.
The component's execute() handles I/O lifecycle (temp dirs, GCS upload, output URIs).
"""

import pickle
from pathlib import Path
import tempfile
from loguru import logger
from gcp_ml_framework.components.ml.train import TrainModel
from google.cloud import bigquery
from importlib.resources import files
import pandas as pd
from third_run.estimator import HousePredictionModel
from typing import cast

class HouseTrainModelStep(TrainModel):
    """Train a house price prediction model."""

    def run(self) -> Path:
        """Train the house price model and save to self._work_dir.

        TrainModel.execute() handles GCS upload of everything in _work_dir.
        """
        logger.info(f"[train_house_model] project={self.project}")

        # Read training data from BigQuery
        logger.info("[train_house_model] Reading training data from BigQuery...")
        client = bigquery.Client(project=self.project)
        query = (
            files("pipelines.house_price.sql")
            .joinpath("house_price_features.sql")
            .read_text()
        )
        df = cast(pd.DataFrame, client.query(query).to_dataframe())

        # Train model
        logger.info("[train_house_model] Training model...")
        model = HousePredictionModel()
        model.fit(df, df["price"])

        # Save model to _work_dir — TrainModel.execute() uploads to GCS
        with tempfile.TemporaryDirectory() as temp_dir:
            local_path = Path(temp_dir) / "model.pkl"
            with open(local_path, "wb") as f:
                pickle.dump(model, f)
            logger.info(f"[train_house_model] Model saved to {local_path}")
            return Path(temp_dir)

if __name__ == "__main__":
    HouseTrainModelStep.cli()
