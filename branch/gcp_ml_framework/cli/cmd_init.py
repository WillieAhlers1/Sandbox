"""gml init — scaffold a new project or pipeline."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from gcp_ml_framework.config import load_config
from gcp_ml_framework.context import MLContext

init_app = typer.Typer(help="Initialise a new project or pipeline.")
console = Console()

# ── Templates ──────────────────────────────────────────────────────────────────

_FRAMEWORK_YAML = """\
team: {team}
project: {project}
gcp:
  dev_project_id: {dev_project}
  staging_project_id: {staging_project}
  prod_project_id: {prod_project}
  region: us-central1
  composer_env:              # fill in your Composer env name
  artifact_registry_host: us-central1-docker.pkg.dev

secrets:
  secret_prefix:             # defaults to namespace token; override only if needed
"""

_PIPELINE_PY = """\
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

# IMPORTANT: Infrastructure provisioning is AUTOMATIC
# ================================================
# When you run: gml run {name} --vertex --sync
# The framework automatically executes (in order):
#
# 1. Terraform Apply (from terraform/ folder)
#    - Creates BigQuery dataset
#    - EXECUTES ALL SQL FILES from sql/BQ/ and sql/FS/ folders
#    - Creates Artifact Registry and Cloud Build
#    - Sets up IAM permissions
#
# 2. Docker Build (if trainer is configured)
#    - Builds trainer container
#    - Pushes to Artifact Registry
#
# 3. KFP Compilation & Submission
#    - Compiles pipeline.py to Vertex AI format
#    - Submits to Vertex AI Pipelines
#
# See terraform/README.md for SQL file management and manual provisioning.

pipeline = (
    PipelineBuilder(name="{name}", schedule="@daily")
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{{bq_dataset}}.raw_events` WHERE dt = '{{run_date}}'",
            output_table="raw_events_extract",
        )
    )
    .transform(
        BQTransform(
            sql_file="sql/{name}_features.sql",
            output_table="{name}_features",
        )
    )
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="{name}_signals",
            entity_id_column="user_id",
        )
    )
    .train(
        TrainModel(
            trainer_image="{{artifact_registry}}/{name}-trainer:latest",
            machine_type="n1-standard-4",
        )
    )
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={{"auc": 0.75}},
        )
    )
    .deploy(
        DeployModel(
            endpoint_name="{name}-endpoint",
        )
    )
    .build()
)
"""

_PIPELINE_CONFIG_YAML = """\
# Pipeline-level config overrides.
# These are merged on top of framework.yaml.
# Only set values that differ from the framework defaults.

# feature_store:
#   sync_schedule: "0 */3 * * *"
"""

_FEATURE_SCHEMA_YAML = """\
entity: user
id_column: user_id
id_type: STRING
feature_groups:
  behavioral:
    description: "Behavioural engagement features"
    features:
      - name: session_count_7d
        type: INT64
      - name: total_purchases_30d
        type: FLOAT64
      - name: days_since_last_login
        type: INT64
  demographic:
    description: "User demographic features"
    features:
      - name: country
        type: STRING
      - name: account_age_days
        type: INT64
"""

_CI_DEV_YAML = """\
name: CI — DEV
on:
  push:
    branches: ["feature/**", "hotfix/**", "fix/**"]

permissions:
  contents: read
  id-token: write

env:
  GML_GCP__DEV_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_DEV }}}}
  GML_TEAM: ${{{{ vars.GML_TEAM }}}}
  GML_PROJECT: ${{{{ vars.GML_PROJECT }}}}

jobs:
  ci-dev:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_DEV }}}}
          service_account: ${{{{ secrets.SA_EMAIL_DEV }}}}
      - run: uv sync
      - run: uv run ruff check gcp_ml_framework tests
      - run: uv run mypy gcp_ml_framework
      - run: uv run pytest tests/unit/ -v
      - run: gml run --compile-only --all
      - run: gml deploy dags
      - run: gml deploy features
"""

_CI_STAGE_YAML = """\
name: CI — STAGE
on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write

env:
  GML_GCP__STAGING_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_STAGING }}}}
  GML_TEAM: ${{{{ vars.GML_TEAM }}}}
  GML_PROJECT: ${{{{ vars.GML_PROJECT }}}}

jobs:
  ci-stage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_STAGING }}}}
          service_account: ${{{{ secrets.SA_EMAIL_STAGING }}}}
      - run: uv sync
      - run: uv run pytest tests/unit/ tests/integration/ -v
      - run: gml deploy dags
      - run: gml deploy features
      - run: gml run --vertex --all --sync
"""

_PROMOTE_YAML = """\
name: Promote — STAGE to PROD
on:
  push:
    tags: ["v[0-9]+.[0-9]+.[0-9]+"]

permissions:
  contents: read
  id-token: write

jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_PROD }}}}
          service_account: ${{{{ secrets.SA_EMAIL_PROD }}}}
        env:
          GML_GCP__STAGING_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_STAGING }}}}
          GML_GCP__PROD_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_PROD }}}}
      - run: uv sync
      - run: gml promote --from main --to prod --tag ${{{{ github.ref_name }}}}
"""

_TEARDOWN_YAML = """\
name: Teardown — DEV ephemeral resources
on:
  pull_request:
    types: [closed]
  schedule:
    - cron: "0 3 * * *"   # daily sweep for inactive branches

permissions:
  contents: read
  id-token: write

jobs:
  teardown:
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule' || github.event.pull_request.merged == true
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_DEV }}}}
          service_account: ${{{{ secrets.SA_EMAIL_DEV }}}}
        env:
          GML_GCP__DEV_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_DEV }}}}
      - run: uv sync
      - run: gml teardown --branch ${{{{ github.head_ref }}}} --confirm
"""

_DOCKERFILE = """\
FROM python:3.11-slim

WORKDIR /app

# Install ML dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    build-essential \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY trainer/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy trainer code
COPY trainer/train.py .

# Run trainer
ENTRYPOINT ["python", "train.py"]
"""

_TRAIN_PY = """\
#!/usr/bin/env python3
\"\"\"Training script for {name} pipeline.\"\"\"

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
    \"\"\"Load training data from BigQuery.\"\"\"
    client = bigquery.Client(project=project_id)
    query = f"SELECT * FROM `{{project_id}}.{{dataset_id}}.{{table_id}}`"
    
    logger.info(f"Loading data from {{project_id}}.{{dataset_id}}.{{table_id}}")
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
    \"\"\"Train a RandomForest model.\"\"\"
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
    \"\"\"Evaluate model performance.\"\"\"
    logger.info("Evaluating model...")
    
    predictions = model.predict(x)
    probabilities = model.predict_proba(x)[:, 1]
    
    metrics = {{
        "accuracy": model.score(x, y),
        "auc": auc(y, probabilities),
        "f1": f1_score(y, predictions),
        "precision": precision_score(y, predictions),
        "recall": recall_score(y, predictions),
    }}
    
    logger.info(f"Metrics: {{json.dumps(metrics, indent=2)}}")
    return metrics


def save_model(model: RandomForestClassifier, output_path: str) -> None:
    \"\"\"Save model to GCS or local path.\"\"\"
    import joblib
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, output_path)
    logger.info(f"Model saved to {{output_path}}")


def main():
    \"\"\"Main training pipeline.\"\"\"
    project_id = os.getenv("GCP_PROJECT_ID", "prj-0n-dta-pt-ai-sandbox")
    dataset_id = os.getenv("BQ_DATASET_ID", "dsci_{name}_main")
    table_id = os.getenv("BQ_TABLE_ID", "{name}_features")
    output_path = os.getenv("MODEL_OUTPUT_PATH", "/tmp/{name}_model.pkl")
    
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
    
    logger.info(f"Training complete. Metrics: {{metrics}}")


if __name__ == "__main__":
    main()
"""

_TRAIN_REQUIREMENTS = """\
numpy>=1.21
pandas>=1.3
scikit-learn>=1.0
google-cloud-bigquery>=3.0
google-cloud-aiplatform>=1.0
joblib>=1.0
"""

_TERRAFORM_MAIN = """\
# Main Terraform configuration for {name} pipeline provisioning
# Includes: BigQuery dataset, SQL execution, Docker image build, Artifact Registry

terraform {{
  required_version = ">= 1.0"
  
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
    null = {{
      source  = "hashicorp/null"
      version = "~> 3.0"
    }}
  }}
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}

# ─────────────────────────────────────────────────────────────────────────────
# Local Variables for Dynamic File Discovery
# ─────────────────────────────────────────────────────────────────────────────

locals {{
  bq_sql_files = try(fileset("${{path.module}}/../sql/BQ", "*.sql"), [])
  fs_sql_files = try(fileset("${{path.module}}/../sql/FS", "*.sql"), [])
}}

# ─────────────────────────────────────────────────────────────────────────────
# BigQuery Dataset
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_dataset" "{name}_dataset" {{
  dataset_id           = var.bigquery_dataset_id
  friendly_name        = "{name} Dataset"
  description          = "Dataset for {name} pipeline"
  location             = var.region
  default_table_expiration_ms = null
  default_partition_expiration_ms = null
  
  labels = merge(
    var.common_labels,
    {{
      pipeline = "{name}"
      managed_by = "terraform"
    }}
  )
}}

# ─────────────────────────────────────────────────────────────────────────────
# BigQuery: Execute SQL Files from BQ folder
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_job" "execute_bq_sql" {{
  for_each = local.bq_sql_files
  
  job_id           = "${{var.bigquery_dataset_id}}-${{replace(each.key, ".sql", "")}}-${{formatdate("YYYY-MM-DD-hhmm", timestamp())}}"
  location         = var.region
  labels           = merge(var.common_labels, {{ pipeline = "{name}", managed_by = "terraform" }})

  query {{
    query          = templatefile("${{path.module}}/../sql/BQ/${{each.key}}", {{
      bq_dataset = var.bigquery_dataset_id
      run_date   = formatdate("YYYY-MM-DD", timestamp())
    }})
    use_legacy_sql = false
  }}

  depends_on = [google_bigquery_dataset.{name}_dataset]
}}

# ─────────────────────────────────────────────────────────────────────────────
# Feature Store: Execute SQL Files from FS folder
# ─────────────────────────────────────────────────────────────────────────────

resource "google_bigquery_job" "execute_fs_sql" {{
  for_each = local.fs_sql_files
  
  job_id           = "${{var.bigquery_dataset_id}}-fs-${{replace(each.key, ".sql", "")}}-${{formatdate("YYYY-MM-DD-hhmm", timestamp())}}"
  location         = var.region
  labels           = merge(var.common_labels, {{ pipeline = "{name}", managed_by = "terraform" }})

  query {{
    query          = templatefile("${{path.module}}/../sql/FS/${{each.key}}", {{
      bq_dataset = var.bigquery_dataset_id
      run_date   = formatdate("YYYY-MM-DD", timestamp())
    }})
    use_legacy_sql = false
  }}

  depends_on = [google_bigquery_dataset.{name}_dataset]
}}

# ─────────────────────────────────────────────────────────────────────────────
# Artifact Registry for Docker Images
# ─────────────────────────────────────────────────────────────────────────────

resource "google_artifact_registry_repository" "{name}_repo" {{
  location      = var.region
  repository_id = replace("{name}", "_", "-")
  description   = "Docker images for {name} pipeline"
  format        = "DOCKER"

  labels = merge(
    var.common_labels,
    {{
      pipeline = "{name}"
      managed_by = "terraform"
    }}
  )
}}

# ─────────────────────────────────────────────────────────────────────────────
# Docker Image Build (Local Execution)
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_build" {{
  provisioner "local-exec" {{
    command     = "docker build -t ${{var.region}}-docker.pkg.dev/${{var.project_id}}/${{replace(\"{name}\", \"_\", \"-\")}}/trainer:latest -f trainer/Dockerfile ."
    working_dir = "${{path.module}}/.."
    interpreter = var.shell_interpreter
  }}

  triggers = {{
    dockerfile_hash = filemd5("${{path.module}}/../trainer/Dockerfile")
  }}

  depends_on = [google_artifact_registry_repository.{name}_repo]
}}

# ─────────────────────────────────────────────────────────────────────────────
# Configure Docker Auth with Artifact Registry
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_auth" {{
  provisioner "local-exec" {{
    command     = "gcloud auth configure-docker ${{var.region}}-docker.pkg.dev"
    interpreter = var.shell_interpreter
  }}

  depends_on = [google_artifact_registry_repository.{name}_repo]
}}

# ─────────────────────────────────────────────────────────────────────────────
# Docker Image Push
# ─────────────────────────────────────────────────────────────────────────────

resource "null_resource" "docker_push" {{
  provisioner "local-exec" {{
    command     = "docker push ${{var.region}}-docker.pkg.dev/${{var.project_id}}/${{replace(\"{name}\", \"_\", \"-\")}}/trainer:latest"
    working_dir = "${{path.module}}/.."
    interpreter = var.shell_interpreter
  }}

  depends_on = [
    null_resource.docker_build,
    null_resource.docker_auth
  ]
}}
"""

_TERRAFORM_VARIABLES = """\
# Terraform variables for {name} pipeline

variable "project_id" {{
  type        = string
  description = "GCP Project ID"
}}

variable "region" {{
  type        = string
  default     = "us-east4"
  description = "GCP region"
}}

variable "bigquery_dataset_id" {{
  type        = string
  default     = "dsci_{name}_main"
  description = "BigQuery dataset ID"
}}

variable "enable_feature_store" {{
  type        = bool
  default     = true
  description = "Enable Vertex AI Feature Store provisioning"
}}

variable "featurestore_node_count" {{
  type        = number
  default     = 1
  description = "Number of nodes for Feature Store online serving"
}}

variable "common_labels" {{
  type        = map(string)
  default     = {{}}
  description = "Common labels for all resources"
}}

variable "shell_interpreter" {{
  type        = list(string)
  default     = ["bash", "-c"]
  description = "Shell interpreter for local-exec"
}}
"""

_TERRAFORM_OUTPUTS = """\
# Terraform outputs for {name} pipeline

output "bigquery_dataset_id" {{
  value       = google_bigquery_dataset.{name}_dataset.dataset_id
  description = "BigQuery dataset ID"
}}

output "executed_bq_sql_jobs" {{
  value       = [for file, job in google_bigquery_job.execute_bq_sql : {{
    sql_file = file
    job_id   = job.job_id
    status   = "executed"
  }}]
  description = "BigQuery SQL jobs executed from sql/BQ/ folder"
}}

output "executed_fs_sql_jobs" {{
  value       = [for file, job in google_bigquery_job.execute_fs_sql : {{
    sql_file = file
    job_id   = job.job_id
    status   = "executed"
  }}]
  description = "Feature Store SQL jobs executed from sql/FS/ folder"
}}

output "artifact_registry_repository" {{
  value       = google_artifact_registry_repository.{name}_repo.repository_id
  description = "Artifact Registry repository ID"
}}

output "artifact_registry_host" {{
  value       = "${{var.region}}-docker.pkg.dev/${{var.project_id}}/${{google_artifact_registry_repository.{name}_repo.repository_id}}"
  description = "Artifact Registry host URL for Docker images"
}}

output "docker_image_uri" {{
  value       = "${{var.region}}-docker.pkg.dev/${{var.project_id}}/${{google_artifact_registry_repository.{name}_repo.repository_id}}/trainer:latest"
  description = "Full Docker image URI for trainer"
}}

output "terraform_state_summary" {{
  value = {{
    dataset_id              = google_bigquery_dataset.{name}_dataset.dataset_id
    artifact_registry_repo  = google_artifact_registry_repository.{name}_repo.repository_id
    bq_sql_files_executed   = length(google_bigquery_job.execute_bq_sql)
    fs_sql_files_executed   = length(google_bigquery_job.execute_fs_sql)
    docker_image_built      = "true (via terraform apply)"
  }}
  description = "Summary of all provisioned resources"
}}
"""

_TERRAFORM_TFVARS_EXAMPLE = """\
# Terraform variables for {name} pipeline
# Copy this to terraform.tfvars and update values

project_id                = "prj-0n-dta-pt-ai-sandbox"
region                    = "us-east4"
bigquery_dataset_id       = "dsci_{name}_main"
enable_feature_store      = true
featurestore_node_count   = 1

common_labels = {{
  team    = "dsci"
  project = "{name}"
  env     = "dev"
}}
"""

_CLOUDBUILD_YAML = """\
# Cloud Build configuration for Docker image building

steps:
  # Build Docker image
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - '${{_TRAINER_IMAGE}}'
      - '-f'
      - 'pipelines/{name}/trainer/Dockerfile'
      - 'pipelines/{name}'

  # Push to Artifact Registry
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'push'
      - '${{_TRAINER_IMAGE}}'

  # Run tests (optional)
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'run'
      - '--rm'
      - '${{_TRAINER_IMAGE}}'
      - '--help'

images:
  - '${{_TRAINER_IMAGE}}'

options:
  machineType: 'N1_HIGHCPU_8'
  logging: CLOUD_LOGGING_ONLY

"""

_GITIGNORE = """\
.env
__pycache__/
*.py[cod]
.mypy_cache/
.ruff_cache/
.pytest_cache/
dist/
*.egg-info/
compiled_pipelines/
.uv/
.terraform/
*.tfstate
*.tfstate.backup
terraform.tfvars
.terraform.lock.hcl
"""


# ── Commands ───────────────────────────────────────────────────────────────────

@init_app.command("project")
def init_project(
    team: str = typer.Argument(..., help="Team slug (e.g. 'dsci')"),
    project: str = typer.Argument(..., help="Project name (e.g. 'churn-pred')"),
    dev_project: str = typer.Option(..., "--dev-project", help="DEV GCP project ID"),
    staging_project: str = typer.Option("", "--staging-project", help="STAGING GCP project ID"),
    prod_project: str = typer.Option("", "--prod-project", help="PROD GCP project ID"),
    output_dir: Path = typer.Option(Path("."), "--out", "-o", help="Output directory"),
) -> None:
    """
    Scaffold a new gcp-ml-framework project.

    Creates framework.yaml, feature_schemas/, CI/CD workflows, and an example pipeline.

    Example:
        gml init project dsci churn-pred --dev-project my-gcp-dev
    """
    staging_project = staging_project or f"{dev_project}-staging"
    prod_project = prod_project or f"{dev_project}-prod"

    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    _write(root / "framework.yaml", _FRAMEWORK_YAML.format(
        team=team, project=project,
        dev_project=dev_project,
        staging_project=staging_project,
        prod_project=prod_project,
    ))
    _write(root / ".python-version", "3.11\n")
    _write(root / ".gitignore", _GITIGNORE)
    _write(root / ".env.example", Path(__file__).parent.parent.parent / ".env.example")
    _write(root / "feature_schemas" / "user.yaml", _FEATURE_SCHEMA_YAML)

    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    _write(wf / "ci-dev.yaml", _CI_DEV_YAML)
    _write(wf / "ci-stage.yaml", _CI_STAGE_YAML)
    _write(wf / "promote.yaml", _PROMOTE_YAML)
    _write(wf / "teardown.yaml", _TEARDOWN_YAML)

    (root / "pipelines").mkdir(exist_ok=True)
    (root / "dags").mkdir(exist_ok=True)
    (root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    _write(root / "tests" / "conftest.py", "# Add shared pytest fixtures here.\n")

    console.print(f"\n[bold green]Project scaffolded at {root}[/bold green]\n")
    console.print("Next steps:")
    console.print("  1. Edit [cyan]framework.yaml[/cyan] — add your Composer env name")
    console.print(f"  2. Run [cyan]gml init pipeline {project}[/cyan] to add a pipeline")
    console.print("  3. Run [cyan]gml context show[/cyan] to verify your setup\n")


@init_app.command("pipeline")
def init_pipeline(
    name: str = typer.Argument(..., help="Pipeline name (snake_case, e.g. 'churn_prediction')"),
    output_dir: Path = typer.Option(Path("pipelines"), "--out", "-o"),
) -> None:
    """
    Scaffold a new pipeline inside an existing project with complete structure.

    Creates:
    - pipeline.py: Pipeline definition
    - config.yaml: Pipeline configuration
    - sql/BQ/: BigQuery SQL files
    - sql/FS/: Feature Store SQL files
    - trainer/: Training container files
    - terraform/: Infrastructure-as-Code for provisioning
    - cloudbuild.yaml: CI/CD configuration

    Example:
        gml init pipeline churn_prediction
    """
    pipeline_dir = output_dir / name
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    # Core pipeline files
    _write(pipeline_dir / "pipeline.py", _PIPELINE_PY.format(name=name))
    _write(pipeline_dir / "config.yaml", _PIPELINE_CONFIG_YAML)
    _write(pipeline_dir / "cloudbuild.yaml", _CLOUDBUILD_YAML.format(name=name))

    # SQL files structure
    bq_sql_dir = pipeline_dir / "sql" / "BQ"
    bq_sql_dir.mkdir(parents=True, exist_ok=True)
    _write(
        bq_sql_dir / "raw_events.sql",
        f"""-- BigQuery: Raw events table creation
-- Naming: dsci-{name}-raw-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.raw_events AS
SELECT
  CAST(FLOOR(1000 + RAND()*9000) AS STRING) AS user_id,
  CURRENT_TIMESTAMP() as event_timestamp,
  CASE FLOOR(RAND()*3)
    WHEN 0 THEN 'login'
    WHEN 1 THEN 'purchase'
    ELSE 'logout'
  END as event_type,
  CAST(FLOOR(RAND()*1000) AS STRING) AS session_id,
  CASE FLOOR(RAND()*3)
    WHEN 0 THEN 'mobile'
    WHEN 1 THEN 'desktop'
    ELSE 'tablet'
  END as device_type,
  CASE FLOOR(RAND()*5)
    WHEN 0 THEN 'US'
    WHEN 1 THEN 'UK'
    WHEN 2 THEN 'CA'
    WHEN 3 THEN 'AU'
    ELSE 'IN'
  END as country
FROM 
  UNNEST(GENERATE_ARRAY(1, 100)) AS n
WHERE
  CURRENT_TIMESTAMP() >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
"""
    )
    
    _write(
        bq_sql_dir / "features_engagement.sql",
        f"""-- BigQuery: Engagement features
-- Naming: dsci-{name}-features-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.features_engagement AS
SELECT
  user_id,
  COUNT(DISTINCT DATE(event_timestamp)) as active_days,
  COUNT(*) as total_events,
  COUNT(DISTINCT session_id) as session_count,
  DATE_DIFF(CURRENT_DATE(), MAX(DATE(event_timestamp)), DAY) as days_since_activity,
  COUNTIF(DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)) > 0 as active_last_7d,
  COUNTIF(DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)) > 0 as active_last_14d
FROM
  `${{bq_dataset}}`.raw_events
GROUP BY
  user_id
"""
    )

    _write(
        bq_sql_dir / "features_behavior.sql",
        f"""-- BigQuery: Behavior features
-- Naming: dsci-{name}-behavior-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.features_behavior AS
SELECT
  user_id,
  COUNTIF(event_type = 'login') as login_count,
  COUNTIF(event_type = 'purchase') as purchase_count,
  SAFE_DIVIDE(COUNTIF(event_type = 'purchase'), COUNT(*)) as purchase_rate,
  COUNT(DISTINCT device_type) as device_diversity,
  CASE 
    WHEN COUNT(DISTINCT device_type) >= 3 THEN 'high_engagement'
    WHEN COUNT(DISTINCT device_type) >= 2 THEN 'medium_engagement'
    ELSE 'low_engagement'
  END as engagement_segment
FROM
  `${{bq_dataset}}`.raw_events
GROUP BY
  user_id
"""
    )

    _write(
        bq_sql_dir / "churn_prediction_features.sql",
        f"""-- BigQuery: Churn prediction features
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.churn_prediction_features AS

WITH base AS (
  SELECT *
  FROM `${{bq_dataset}}`.raw_events
  WHERE DATE(event_timestamp) = '${{run_date}}'
),

aggregated AS (
  SELECT
    user_id,
    COUNT(*) AS total_events,
    COUNTIF(event_type = 'login') AS login_events,
    COUNTIF(event_type = 'purchase') AS purchase_events,
    COUNT(DISTINCT session_id) AS session_count,
    MAX(event_timestamp) AS last_event_time
  FROM base
  GROUP BY user_id
),

labeled AS (
  SELECT
    *,
    CASE
      WHEN total_events < 3 AND login_events < 2 THEN 1
      ELSE 0
    END AS is_churned
  FROM aggregated
)

SELECT *
FROM labeled
"""
    )

    _write(bq_sql_dir / "README.md", """# BigQuery SQL Files

These SQL files create BigQuery tables for the feature engineering pipeline.

## Naming Convention
- Pattern: `dsci-{project}-{component}-{branch}`
- Example: `dsci-churn-prediction-raw-main`

## Files
- `raw_events.sql`: Extract raw events data
- `features_engagement.sql`: User engagement metrics
- `features_behavior.sql`: User behavior patterns

## Best Practices
1. Use `CURRENT_TIMESTAMP()` for dynamic timestamps
2. Reference datasets with `{{{{project_id}}}}.{{{{bq_dataset}}}}`
3. Handle NULL values explicitly
4. Use SAFE_DIVIDE for division operations
5. Include data quality checks
""")

    # BigQuery: User features table (example)
    _write(
        bq_sql_dir / "raw_user_features.sql",
        f"""-- BigQuery: Raw user features
-- Naming: dsci-{name}-user-features-main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.raw_user_features AS
SELECT
  CAST(FLOOR(1000 + RAND()*9000) AS STRING) AS entity_id,
  CAST(FLOOR(RAND()*10) AS INT64) AS session_count_7d,
  CAST(FLOOR(RAND()*30) AS INT64) AS session_count_30d,
  CAST(FLOOR(RAND()*50) AS INT64) AS total_purchases_30d,
  CAST(FLOOR(RAND()*60) AS INT64) AS days_since_last_login,
  CAST(FLOOR(RAND()*5) AS INT64) AS support_tickets_90d,
  CAST(RAND()*3600 AS FLOAT64) AS avg_session_duration_s,
  CAST(FLOOR(RAND()*2) AS BOOLEAN) AS churned_within_30d,
  DATE_SUB(CURRENT_DATE(), INTERVAL CAST(FLOOR(RAND()*30) AS INT64) DAY) AS event_date
FROM UNNEST(GENERATE_ARRAY(1, 1000)) AS n
"""
    )

    # Feature Store SQL files
    fs_sql_dir = pipeline_dir / "sql" / "FS"
    fs_sql_dir.mkdir(parents=True, exist_ok=True)
    
    _write(
        fs_sql_dir / "entity_user.sql",
        f"""-- Feature Store: User entity definition
-- Entity: fs_dsci_{name}_user_main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.entity_user AS
SELECT DISTINCT
  user_id as entity_id,
  CURRENT_TIMESTAMP() as created_timestamp
FROM
  `${{bq_dataset}}`.raw_events
"""
    )
    
    _write(
        fs_sql_dir / "entity_session.sql",
        f"""-- Feature Store: Session entity definition
-- Entity: fs_dsci_{name}_session_main
-- This table is CREATED by Terraform when provisioning

CREATE OR REPLACE TABLE `${{bq_dataset}}`.entity_session AS
SELECT DISTINCT
  session_id as entity_id,
  CURRENT_TIMESTAMP() as created_timestamp
FROM
  `${{bq_dataset}}`.raw_events
"""
    )

    _write(fs_sql_dir / "README.md", """# Feature Store SQL Files

These SQL files define Feature Store entities for the pipeline.

## Naming Convention
- Pattern: `fs_{team}_{project}_{entity}_{branch}`
- Example: `fs_dsci_churn_prediction_user_main`

## Entity Files
- `entity_user.sql`: User entity definition
- `entity_session.sql`: Session entity definition

## Best Practices
1. Entity files must have `entity_id` column
2. Include timestamp columns
3. Use DISTINCT to prevent duplicates
4. Match schema in Feature Store feature exports
""")

    # Trainer Docker files
    trainer_dir = pipeline_dir / "trainer"
    trainer_dir.mkdir(parents=True, exist_ok=True)
    _write(trainer_dir / "Dockerfile", _DOCKERFILE.format(name=name))
    _write(trainer_dir / "train.py", _TRAIN_PY.format(name=name))
    _write(trainer_dir / "requirements.txt", _TRAIN_REQUIREMENTS)
    _write(trainer_dir / "README.md", f"""# Trainer Container

This folder contains the training code and Docker configuration for the {name} pipeline.

## Files
- `Dockerfile`: Container configuration
- `train.py`: Training script
- `requirements.txt`: Python dependencies

## Building the Image
```bash
docker build -t {name}-trainer:latest .
```

## Running Locally
```bash
docker run --rm \\
  -e GCP_PROJECT_ID=prj-xxx \\
  -e BQ_DATASET_ID=dsci_{name}_main \\
  {name}-trainer:latest
```

## Environment Variables
- `GCP_PROJECT_ID`: GCP project ID
- `BQ_DATASET_ID`: BigQuery dataset
- `BQ_TABLE_ID`: Training data table
- `MODEL_OUTPUT_PATH`: Where to save the trained model
""")

    # Terraform Infrastructure-as-Code
    terraform_dir = pipeline_dir / "terraform"
    terraform_dir.mkdir(parents=True, exist_ok=True)
    
    _write(
        terraform_dir / "main.tf",
        _TERRAFORM_MAIN.format(name=name)
    )
    _write(
        terraform_dir / "variables.tf",
        _TERRAFORM_VARIABLES.format(name=name)
    )
    _write(
        terraform_dir / "outputs.tf",
        _TERRAFORM_OUTPUTS.format(name=name)
    )
    _write(
        terraform_dir / "terraform.tfvars.example",
        _TERRAFORM_TFVARS_EXAMPLE.format(name=name)
    )
    
    # Try to auto-populate terraform.tfvars from framework.yaml
    try:
        cfg = load_config()  # Load framework.yaml from current directory
        tfvars_content = f"""# Auto-generated Terraform variables (from framework.yaml)
# Provisioning: BigQuery, SQL execution, Docker build, Artifact Registry

project_id                = "{cfg.gcp.dev_project_id}"
region                    = "{cfg.gcp.region}"
bigquery_dataset_id       = "dsci_{name}_main"
enable_feature_store      = true
featurestore_node_count   = 1

common_labels = {{
  team    = "{cfg.team}"
  project = "{name}"
  env     = "dev"
}}
"""
        _write(terraform_dir / "terraform.tfvars", tfvars_content)
    except Exception:
        # If framework.yaml not found or loading fails, just skip
        # User will need to copy and edit tfvars.example manually
        pass
    
    _write(
        terraform_dir / "README.md",
        f"""# Terraform - Infrastructure as Code for {name} Pipeline

Automatic provisioning of GCP resources for the {name} pipeline.

## How It Works

This Terraform configuration is **automatically executed** when you run:

```bash
gml run {name} --vertex --sync
```

The pipeline execution follows this sequence:

1. **Terraform Apply** (First step - automatic)
   - Creates BigQuery dataset
   - **Executes ALL SQL files** from `sql/BQ/` folder
   - Creates Artifact Registry
   - Sets up Cloud Build triggers
   - Grants IAM permissions

2. **Docker Build** (Automatic)
   - Builds trainer container from Dockerfile
   - Pushes to Artifact Registry

3. **KFP Compilation** (Automatic)
   - Compiles pipeline.py to Vertex AI format

4. **Pipeline Submission** (Automatic)
   - Submits to Vertex AI Pipelines
   - Waits for completion (--sync)

## SQL File Execution

The key feature: **SQL files are executed dynamically at runtime**.

### How SQL Discovery Works

Terraform automatically discovers and executes:
- **All files** in `sql/BQ/*.sql` → Creates tables
- **All files** in `sql/FS/*.sql` → Creates Feature Store entities

You can:
- ✅ Add new SQL files → Automatically executed
- ✅ Rename SQL files → Still executed
- ✅ Remove SQL files → No error, just skipped
- ✅ Modify SQL content → Changes applied on next run

### Example

If you have these files:
```
sql/BQ/
├── raw_data.sql                    ← Auto-executed
├── daily_features.sql              ← Auto-executed
└── metrics.sql                     ← Auto-executed

sql/FS/
└── user_entity.sql                 ← Auto-executed
```

Running `gml run {name}` will execute all 4 files with no additional configuration needed.

## Manual Terraform Operations

For debugging or testing, you can run Terraform directly:

### Initialize
```bash
cd terraform
terraform init
```

### Plan (see what will happen)
```bash
terraform plan
```

### Apply Manually
```bash
terraform apply
```

(Usually not needed - `gml run` does this automatically)

### Destroy (clean up)
```bash
terraform destroy
```

## Configuration

Edit `terraform.tfvars` with your GCP details:

```hcl
project_id                = "prj-0n-dta-pt-ai-sandbox"
region                    = "us-east4"
bigquery_dataset_id       = "dsci_{name}_main"
github_owner              = "your-github-org"
github_repo               = "your-github-repo"
git_branch                = "main"
service_account_email     = "gc-sa-xxx@prj-xxx.iam.gserviceaccount.com"
enable_feature_store      = true
featurestore_node_count   = 1

common_labels = {{
  team    = "dsci"
  project = "{name}"
  env     = "dev"
}}
```

## Cost Tracking

All resources are labeled with `pipeline = "{name}"` and `managed_by = "terraform"`.

View costs:
```bash
gcloud billing accounts list
gcloud compute project-info describe PROJECT_ID \\
  --format='value(labels.pipeline)'
```

## Troubleshooting

### SQL Execution Failed
Check the SQL syntax in your files:
```bash
# Validate locally
bq query --use_legacy_sql=false < sql/BQ/raw_data.sql --dry_run
```

### Terraform State Issues
If state gets corrupted:
```bash
rm -rf .terraform .terraform.lock.hcl terraform.tfstate*
terraform init
terraform apply
```

### Permission Denied
Ensure service account has roles:
- roles/bigquery.admin
- roles/aiplatform.admin
- roles/artifactregistry.admin

## Next Steps

1. **Customize SQL files** in `sql/BQ/` and `sql/FS/`
2. **Edit pipeline.py** to define your workflow
3. **Update trainer.py** with your model code
4. **Run pipeline**: `gml run {name} --vertex --sync`

---

**Important**: 
- ✅ terraform.tfvars **auto-created** from framework.yaml
- ✅ `gml run {name} --vertex --sync` runs **terraform apply -auto-approve** (no prompts)
- ✅ All SQL files in sql/BQ/ and sql/FS/ execute automatically
- 📝 Only customize terraform.tfvars if you need non-standard values
"""
    )

    console.print(f"\n[bold green]✓ Pipeline '{name}' scaffolded at {pipeline_dir}[/bold green]\n")
    
    console.print("[cyan]Directory Structure:[/cyan]")
    console.print(f"""
{name}/
├── pipeline.py                    # Pipeline definition
├── config.yaml                    # Pipeline configuration
├── cloudbuild.yaml                # CI/CD configuration
│
├── sql/
│   ├── BQ/                        # BigQuery SQL files
│   │   ├── raw_events.sql
│   │   ├── features_engagement.sql
│   │   ├── features_behavior.sql
│   │   └── README.md
│   │
│   └── FS/                        # Feature Store SQL files
│       ├── entity_user.sql
│       ├── entity_session.sql
│       └── README.md
│
├── trainer/                       # Training container
│   ├── Dockerfile
│   ├── train.py
│   ├── requirements.txt
│   └── README.md
│
└── terraform/                     # Infrastructure as Code
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── terraform.tfvars.example
    └── README.md
""")

    console.print("[cyan]Next Steps:[/cyan]\n")
    console.print(f"  1. Edit [bold]pipelines/{name}/pipeline.py[/bold] to define pipeline steps")
    console.print(f"  2. Edit [bold]pipelines/{name}/sql/BQ/*.sql[/bold] for data queries")
    console.print(f"  3. Edit [bold]pipelines/{name}/trainer/train.py[/bold] for model training")
    console.print(f"  4. Customize [bold]pipelines/{name}/terraform/terraform.tfvars[/bold] (github_owner/repo)")
    console.print(f"  5. Run: [bold]gml run {name} --vertex --sync[/bold]")
    console.print(f"\n[yellow]Note:[/yellow] terraform.tfvars was auto-created from framework.yaml")
    console.print(f"      Terraform applies automatically with -auto-approve (no prompts)\n")



def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, Path):
        if content.exists():
            path.write_text(content.read_text())
    else:
        path.write_text(content)
