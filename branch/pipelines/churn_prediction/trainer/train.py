#!/usr/bin/env python3
"""Training script for churn_prediction pipeline."""

import os
import logging
from pathlib import Path
import json

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import auc, f1_score, precision_score, recall_score
from google.cloud import bigquery, aiplatform

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_training_data(project_id: str, dataset_id: str, table_id: str) -> tuple[pd.DataFrame, np.ndarray]:
    """Load training data from BigQuery."""
    client = bigquery.Client(project=project_id)
    query = f"SELECT * FROM `{project_id}.{dataset_id}.{table_id}`"
    
    logger.info(f"Loading data from {project_id}.{dataset_id}.{table_id}")
    df = client.query(query).to_dataframe()
    
    # Separate features from target
    if 'label' in df.columns:
        x = df.drop('label', axis=1)
        y = df['label'].values
    else:
        logger.warning("No 'label' column found, using all columns for features")
        x = df
        y = None
    
    return x, y


def train_model(x: pd.DataFrame, y: np.ndarray) -> RandomForestClassifier:
    """Train a RandomForest model."""
    logger.info("Training RandomForest model...")
    
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=5,
        random_state=42,
        n_jobs=-1
    )
    
    model.fit(x, y)
    logger.info("Model training complete")
    
    return model


def evaluate_model(model: RandomForestClassifier, x: pd.DataFrame, y: np.ndarray) -> dict:
    """Evaluate model performance."""
    logger.info("Evaluating model...")
    
    predictions = model.predict(x)
    probabilities = model.predict_proba(x)[:, 1]
    
    metrics = {
        "accuracy": model.score(x, y),
        "auc": auc(y, probabilities),
        "f1": f1_score(y, predictions),
        "precision": precision_score(y, predictions),
        "recall": recall_score(y, predictions),
    }
    
    logger.info(f"Metrics: {json.dumps(metrics, indent=2)}")
    return metrics


def save_model(model: RandomForestClassifier, output_path: str) -> None:
    """Save model to GCS or local path."""
    import joblib
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_path)
    logger.info(f"Model saved to {output_path}")


def main():
    """Main training pipeline."""
    project_id = os.getenv("GCP_PROJECT_ID", "prj-0n-dta-pt-ai-sandbox")
    dataset_id = os.getenv("BQ_DATASET_ID", "dsci_churn_prediction_main")
    table_id = os.getenv("BQ_TABLE_ID", "churn_prediction_features")
    output_path = os.getenv("MODEL_OUTPUT_PATH", "/tmp/churn_prediction_model.pkl")
    
    # Load data
    x, y = load_training_data(project_id, dataset_id, table_id)
    
    if y is None:
        logger.error("No target variable found. Cannot train model.")
        return
    
    # Train model
    model = train_model(x, y)
    
    # Evaluate
    metrics = evaluate_model(model, x, y)
    
    # Save model
    save_model(model, output_path)
    
    logger.info(f"Training complete. Metrics: {metrics}")


if __name__ == "__main__":
    main()
