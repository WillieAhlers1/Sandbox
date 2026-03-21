"""Reusable model evaluation logic — extracted from evaluate component."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger


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
    import hashlib
    import pickle
    import tempfile

    from google.cloud import bigquery, storage
    from sklearn.metrics import f1_score, roc_auc_score

    # Read eval dataset from BigQuery
    bq_client = bigquery.Client(project=project)
    df = bq_client.query(f"SELECT * FROM `{eval_dataset_uri}`").to_dataframe()
    logger.info(f"Loaded {len(df)} rows from {eval_dataset_uri}")

    x_features = df.drop(columns=["label", "user_id", "feature_timestamp"], errors="ignore")
    y = df["label"]

    # Download model.pkl from GCS
    parts = model_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path = (parts[1] + "/model.pkl") if len(parts) > 1 else "model.pkl"
    gcs_client = storage.Client(project=project)
    blob = gcs_client.bucket(bucket_name).blob(blob_path)
    with tempfile.NamedTemporaryFile(suffix=".pkl") as tmp:
        blob.download_to_filename(tmp.name)
        with open(tmp.name, "rb") as f:
            model = pickle.load(f)
    logger.info(f"Loaded model from {model_uri}/model.pkl")

    # Compute metrics
    computed: dict[str, float] = {}
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x_features)[:, 1]
    else:
        proba = model.predict(x_features)
    preds = (proba > 0.5).astype(int)

    if "auc" in metrics:
        computed["auc"] = round(float(roc_auc_score(y, proba)), 4)
    if "f1" in metrics:
        computed["f1"] = round(float(f1_score(y, preds)), 4)
    logger.info(f"Metrics: {computed}")

    # Apply gates
    failures = []
    for metric, threshold in gate.items():
        if metric in computed and computed[metric] < threshold:
            failures.append(f"{metric}={computed[metric]:.4f} < threshold={threshold}")

    if failures:
        raise ValueError(f"Model failed evaluation gates: {', '.join(failures)}")

    # Log to Vertex AI Experiments (best-effort)
    try:
        from google.cloud import aiplatform
        aiplatform.init(project=project, location=region, experiment=experiment_name)
        run_id = "eval-" + hashlib.md5(model_uri.encode()).hexdigest()[:8]
        aiplatform.start_run(run=run_id)
        aiplatform.log_metrics(computed)
        aiplatform.end_run()
        logger.info(f"Logged metrics to experiment '{experiment_name}' run '{run_id}'")
    except Exception as e:
        logger.info(f"Warning: could not log to experiments: {e}")

    Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_uri_path, "w") as f:
        f.write(json.dumps(computed))
