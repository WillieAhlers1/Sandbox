"""Reusable model evaluation logic — extracted from evaluate component."""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from loguru import logger


def _compute_regression_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    requested: list[str],
) -> dict[str, float]:
    """Compute regression metrics."""
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    available = {
        "rmse": lambda: round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": lambda: round(float(mean_absolute_error(y_true, y_pred)), 4),
        "r2": lambda: round(float(r2_score(y_true, y_pred)), 4),
        "mse": lambda: round(float(mean_squared_error(y_true, y_pred)), 4),
    }
    return {m: available[m]() for m in requested if m in available}


def _compute_classification_metrics(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    requested: list[str],
) -> dict[str, float]:
    """Compute classification metrics."""
    from sklearn.metrics import f1_score, roc_auc_score

    preds = (y_proba > 0.5).astype(int)
    available = {
        "auc": lambda: round(float(roc_auc_score(y_true, y_proba)), 4),
        "f1": lambda: round(float(f1_score(y_true, preds)), 4),
    }
    return {m: available[m]() for m in requested if m in available}


def run_evaluate(
    *,
    project: str,
    region: str,
    model_uri: str,
    eval_dataset_uri: str,
    metrics: list[str],
    gate: dict[str, float],
    experiment_name: str,
    output_uri_path: str,
) -> None:
    """Evaluate a model against a BQ eval dataset and apply metric gates."""
    import tempfile

    from google.cloud import bigquery, storage

    # Read eval dataset from BigQuery
    bq_client = bigquery.Client(project=project)
    df = bq_client.query(f"SELECT * FROM `{eval_dataset_uri}`").to_dataframe()
    logger.info("Loaded %d rows from %s", len(df), eval_dataset_uri)

    # Determine target column
    target_col = "price" if "price" in df.columns else "label"
    y_true = df[target_col].values
    x_features = df.drop(columns=[target_col], errors="ignore")

    # Drop non-feature columns
    drop_cols = [
        c for c in ["user_id", "feature_timestamp", "processed_at"]
        if c in x_features.columns
    ]
    x_features = x_features.drop(columns=drop_cols, errors="ignore")

    # Download model.pkl from GCS
    parts = model_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path = (parts[1] + "/model.pkl") if len(parts) > 1 else "model.pkl"
    gcs_client = storage.Client(project=project)
    blob = gcs_client.bucket(bucket_name).blob(blob_path)
    with tempfile.NamedTemporaryFile(suffix=".pkl") as tmp:
        blob.download_to_filename(tmp.name)
        with open(tmp.name, "rb") as f:
            model = pickle.load(f)  # noqa: S301
    logger.info("Loaded model from %s/model.pkl", model_uri)

    # Detect model type and compute metrics
    if hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(x_features)[:, 1]
        computed = _compute_classification_metrics(y_true, y_proba, metrics)
    else:
        y_pred = model.predict(x_features)
        # Handle models that return DataFrames (like HousePredictionModel)
        if hasattr(y_pred, "values"):
            if hasattr(y_pred, "columns") and target_col in y_pred.columns:
                y_pred = y_pred[target_col].values
            else:
                y_pred = y_pred.values.ravel()
        computed = _compute_regression_metrics(y_true, y_pred, metrics)

    logger.info("Metrics: %s", computed)

    # Apply gates — direction-aware for regression vs classification
    regression_lower_is_better = {"rmse", "mae", "mse"}
    failures = []
    for metric, threshold in gate.items():
        if metric in computed:
            if metric in regression_lower_is_better:
                if computed[metric] > threshold:
                    failures.append(
                        f"{metric}={computed[metric]:.4f} > threshold={threshold}"
                    )
            elif computed[metric] < threshold:
                failures.append(
                    f"{metric}={computed[metric]:.4f} < threshold={threshold}"
                )

    if failures:
        raise ValueError(f"Model failed evaluation gates: {', '.join(failures)}")

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_uri_path).write_text(json.dumps(computed))
