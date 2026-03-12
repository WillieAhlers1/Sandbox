"""CLI entrypoint for the TrainModel KFP component.

This runs inside the component-base container. It submits a Vertex AI
CustomJob that launches the user's trainer image (e.g. training_pipeline-trainer).

Usage (called by KFP at runtime):
    python -m gcp_ml_framework.components.ml.train_entrypoint \
        --project my-project \
        --region us-east4 \
        --staging-bucket gs://my-bucket \
        --experiment-name my-experiment \
        --job-name my-job \
        --trainer-image us-east4-docker.pkg.dev/.../trainer:latest \
        --machine-type n2-standard-4 \
        --model-output-uri gs://my-bucket/models/my-pipeline \
        --hyperparameters '{"learning_rate": 0.01}' \
        --output-uri-path /tmp/kfp/outputs/Output/data
"""

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from google.cloud import aiplatform, storage


def main() -> None:
    parser = argparse.ArgumentParser(description="TrainModel component entrypoint")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--staging-bucket", required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--trainer-image", required=True)
    parser.add_argument("--machine-type", default="n2-standard-4")
    parser.add_argument("--accelerator-type", default="")
    parser.add_argument("--accelerator-count", type=int, default=0)
    parser.add_argument("--trainer-args", default="[]", help="JSON list")
    parser.add_argument("--hyperparameters", default="{}", help="JSON dict")
    parser.add_argument("--model-output-uri", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--dataset-uri", default="")
    # KFP output path — the container_component writes the return value here
    parser.add_argument("--output-uri-path", required=True)

    args = parser.parse_args()

    aiplatform.init(
        project=args.project,
        location=args.region,
        staging_bucket=args.staging_bucket,
        experiment=args.experiment_name,
    )

    versioned_uri = args.model_output_uri
    if args.run_id:
        versioned_uri = f"{args.model_output_uri.rstrip('/')}/{args.run_id}"

    with TemporaryDirectory() as temp_dir:
        cli_args = json.loads(args.trainer_args) + [f"--model-output={temp_dir}"]
        if args.dataset_uri:
            cli_args.append(f"--dataset-path={args.dataset_uri}")
        for k, v in json.loads(args.hyperparameters).items():
            cli_args.append(f"--{k}={v}")

        worker_pool: dict = {
            "machine_spec": {"machine_type": args.machine_type},
            "replica_count": 1,
            "container_spec": {"image_uri": args.trainer_image, "args": cli_args},
        }
        if args.accelerator_type and args.accelerator_count > 0:
            worker_pool["machine_spec"]["accelerator_type"] = args.accelerator_type
            worker_pool["machine_spec"]["accelerator_count"] = args.accelerator_count

        job = aiplatform.CustomJob(
            display_name=args.job_name,
            worker_pool_specs=[worker_pool],
            staging_bucket=args.staging_bucket,
        )
        job.run(sync=True, experiment=args.experiment_name)

        # Upload local artifacts to GCS
        parts = versioned_uri.replace("gs://", "").split("/", 1)
        bucket_name = parts[0]
        gcs_client = storage.Client(project=args.project)
        for local_path in Path(temp_dir).glob("*"):
            blob_path = f"{parts[1].rstrip('/')}/{local_path.name}"
            blob = gcs_client.bucket(bucket_name).blob(blob_path)
            blob.upload_from_filename(local_path)
        print(f"[trainer] Model uploaded to {versioned_uri}/model.pkl")

    # Write the output for KFP
    output_path = Path(args.output_uri_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(args.model_output_uri)


if __name__ == "__main__":
    main()
