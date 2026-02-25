"""Minimal churn model trainer for the example pipeline.

Accepts CLI args from the Vertex AI CustomJob worker pool and writes
a placeholder model artifact to GCS.
"""

import argparse
import json
import os


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", required=True)
    parser.add_argument("--dataset-path", default="")
    # Accept arbitrary hyperparameters
    parser.add_argument("--learning_rate", type=float, default=0.05)
    parser.add_argument("--max_depth", type=int, default=6)
    parser.add_argument("--n_estimators", type=int, default=300)
    parser.add_argument("--subsample", type=float, default=0.8)
    args, _ = parser.parse_known_args()

    print(f"[trainer] model-output: {args.model_output}")
    print(f"[trainer] dataset-path: {args.dataset_path}")
    print(f"[trainer] hyperparameters: lr={args.learning_rate}, "
          f"max_depth={args.max_depth}, n_estimators={args.n_estimators}")

    model = {
        "framework": "xgboost-placeholder",
        "hyperparameters": {
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "n_estimators": args.n_estimators,
            "subsample": args.subsample,
        },
    }

    # Write model artifact to GCS via gsutil or local path
    output = args.model_output
    if output.startswith("gs://"):
        local_path = "/tmp/model.json"
        with open(local_path, "w") as f:
            json.dump(model, f)
        os.system(f"gsutil cp {local_path} {output}/model.json")
        print(f"[trainer] Model uploaded to {output}/model.json")
    else:
        os.makedirs(output, exist_ok=True)
        with open(os.path.join(output, "model.json"), "w") as f:
            json.dump(model, f)
        print(f"[trainer] Model saved to {output}/model.json")


if __name__ == "__main__":
    main()
