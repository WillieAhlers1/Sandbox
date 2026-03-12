"""Churn model trainer for the example pipeline.

Accepts CLI args from the Vertex AI CustomJob worker pool.
Reads training data from BigQuery, trains a LogisticRegression model,
and saves the model as a pickle artifact to GCS.
"""

import pickle

from google.cloud import bigquery
from typer import Typer
from loguru import logger
from second_run.estimator import HousePredictionModel
from importlib.resources import files
from google.cloud import bigquery
from pathlib import Path

# Typer CLI app
app = Typer()

@app.command()
def main(
    model_output: str,  # local path where the model artifact will be saved
    project_id: str
) -> None:
    
    logger.info(f"[trainer] model-output: {model_output}")

    # Step 1: Read Data from BigQuery
    client = bigquery.Client(project=project_id)
    query = (
        files("pipelines.training_pipeline.sql")
        .joinpath("training_pipeline_features.sql").read_text()
    )
    df = client.query(query).to_dataframe()    
    
    # Step 2: Train model
    model = HousePredictionModel()    
    model.fit(df, df['price'])

    # Save model.pkl to GCS or local
    local_path = Path(model_output) / "model.pkl"
    with open(local_path, "wb") as f:
        pickle.dump(model, f)



if __name__ == "__main__":
    app()
