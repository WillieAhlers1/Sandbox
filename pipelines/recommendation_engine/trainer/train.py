"""Recommendation model trainer — simple collaborative filtering with NMF."""

import argparse
import os
import pickle

import numpy as np
import pandas as pd
from sklearn.decomposition import NMF


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--dataset-path", default="")
    parser.add_argument("--n_components", type=int, default=10)
    parser.add_argument("--max_iter", type=int, default=200)
    args, _ = parser.parse_known_args()

    print(f"[trainer] model-output: {args.model_output}")
    print(f"[trainer] n_components: {args.n_components}")

    # Build user-item interaction matrix
    if args.dataset_path:
        df = pd.read_csv(args.dataset_path)
    else:
        raise ValueError("--dataset-path is required")

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
    os.makedirs(output, exist_ok=True)
    model_path = os.path.join(output, "model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)
    print(f"[trainer] Model saved to {model_path}")


if __name__ == "__main__":
    main()
