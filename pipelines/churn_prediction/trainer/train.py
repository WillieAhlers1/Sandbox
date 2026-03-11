"""Churn model trainer for the example pipeline.

Accepts CLI args from the Vertex AI CustomJob worker pool.
Reads training data from BigQuery, trains a LogisticRegression model,
and saves the model as a pickle artifact to GCS.
"""

import argparse
import pickle

from google.cloud import bigquery, storage
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--dataset-path", default="")
    # LogisticRegression hyperparameters (passed by TrainModel via --key=value)
    parser.add_argument("--C", type=float, default=1.0)
    parser.add_argument("--max_iter", type=int, default=1000)
    parser.add_argument("--solver", type=str, default="lbfgs")
    args, _ = parser.parse_known_args()

    print(f"[trainer] model-output: {args.model_output}")
    print(f"[trainer] dataset-path: {args.dataset_path}")

    # Read training data from BigQuery
    dataset_path = args.dataset_path
    if not dataset_path:
        raise ValueError("--dataset-path is required (fully-qualified BQ table)")

    # Extract project from the fully-qualified table name (project.dataset.table)
    project = dataset_path.split(".")[0]
    bq_client = bigquery.Client(project=project)
    df = bq_client.query(f"SELECT * FROM `{dataset_path}`").to_dataframe()
    print(f"[trainer] Loaded {len(df)} rows from {dataset_path}")

    # Prepare features and target
    drop_cols = [c for c in ["label", "user_id", "feature_timestamp"] if c in df.columns]
    X = df.drop(columns=drop_cols)
    y = df["label"]
    print(f"[trainer] Features: {list(X.columns)}")
    print(f"[trainer] Label distribution: {y.value_counts().to_dict()}")

    # Train a sklearn pipeline (StandardScaler + LogisticRegression)
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(
            C=args.C, max_iter=args.max_iter, solver=args.solver, random_state=42
        )),
    ])
    model.fit(X, y)

    train_proba = model.predict_proba(X)[:, 1]
    train_preds = (train_proba > 0.5).astype(int)
    train_acc = (train_preds == y).mean()
    print(f"[trainer] Train accuracy: {train_acc:.4f}")

    # Save model.pkl to GCS or local
    output = args.model_output
    local_path = "/tmp/model.pkl"
    with open(local_path, "wb") as f:
        pickle.dump(model, f)

    if output.startswith("gs://"):
        parts = output.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_path = (parts[1] + "/model.pkl") if len(parts) > 1 else "model.pkl"
        gcs_client = storage.Client(project=project)
        blob = gcs_client.bucket(bucket_name).blob(blob_path)
        blob.upload_from_filename(local_path)
        print(f"[trainer] Model uploaded to {output}/model.pkl")
    else:
        import os
        import shutil
        os.makedirs(output, exist_ok=True)
        shutil.copy(local_path, os.path.join(output, "model.pkl"))
        print(f"[trainer] Model saved to {output}/model.pkl")


if __name__ == "__main__":
    main()
