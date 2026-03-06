"""Recommendation model trainer — simple collaborative filtering with NMF.

Reads training data from BigQuery, builds a user-item interaction matrix,
trains an NMF model, and saves the model artifact to GCS.
"""

import argparse
import os
import pickle

import numpy as np
import pandas as pd
from google.cloud import bigquery, storage
from sklearn.decomposition import NMF


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--dataset-path", default="")
    parser.add_argument("--n_components", type=int, default=10)
    parser.add_argument("--max_iter", type=int, default=200)
    args, _ = parser.parse_known_args()

    print(f"[trainer] model-output: {args.model_output}")
    print(f"[trainer] dataset-path: {args.dataset_path}")
    print(f"[trainer] n_components: {args.n_components}")

    # Read training data from BigQuery (dataset_path is a fully-qualified table)
    dataset_path = args.dataset_path
    if not dataset_path:
        raise ValueError("--dataset-path is required (fully-qualified BQ table)")

    project = dataset_path.split(".")[0]
    bq_client = bigquery.Client(project=project)
    df = bq_client.query(f"SELECT * FROM `{dataset_path}`").to_dataframe()
    print(f"[trainer] Loaded {len(df)} rows from {dataset_path}")

    # Create interaction matrix
    df["score"] = df["interaction_type"].map({"view": 1, "purchase": 3}).fillna(1)
    interaction_matrix = df.pivot_table(
        index="user_id", columns="item_id", values="score", aggfunc="sum", fill_value=0
    )

    # Train NMF model
    model = NMF(n_components=min(args.n_components, min(interaction_matrix.shape)),
                max_iter=args.max_iter, random_state=42)
    W = model.fit_transform(interaction_matrix.values)
    H = model.components_

    print(f"[trainer] Matrix shape: {interaction_matrix.shape}")
    print(f"[trainer] Reconstruction error: {model.reconstruction_err_:.4f}")

    # Save model
    model_data = {
        "model": model,
        "W": W,
        "H": H,
        "users": list(interaction_matrix.index),
        "items": list(interaction_matrix.columns),
    }

    output = args.model_output
    local_path = "/tmp/reco_model.pkl"
    with open(local_path, "wb") as f:
        pickle.dump(model_data, f)

    if output.startswith("gs://"):
        parts = output.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        blob_path = (parts[1] + "/model.pkl") if len(parts) > 1 else "model.pkl"
        gcs_client = storage.Client(project=project)
        blob = gcs_client.bucket(bucket_name).blob(blob_path)
        blob.upload_from_filename(local_path)
        print(f"[trainer] Model uploaded to {output}/model.pkl")
    else:
        os.makedirs(output, exist_ok=True)
        import shutil
        shutil.copy(local_path, os.path.join(output, "model.pkl"))
        print(f"[trainer] Model saved to {output}/model.pkl")


if __name__ == "__main__":
    main()
