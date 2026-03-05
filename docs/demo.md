# End-to-End Demo — GCP ML/Data Orchestration Platform

> A step-by-step walkthrough of setting up and running both example pipelines
> (sales_analytics and churn_prediction) from a clean clone to verified GCP
> execution.
>
> Audience: New team members, reviewers, or anyone validating the platform.
>
> Last tested: 2026-03-05 on branch `os_experimental`
> GCP Project: `gcp-gap-demo-dev` (us-central1)

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and Install](#2-clone-and-install)
3. [Understand the Project Structure](#3-understand-the-project-structure)
4. [Configure the Project](#4-configure-the-project)
5. [Verify Context Resolution](#5-verify-context-resolution)
6. [Run Tests](#6-run-tests)
7. [Local Execution (No GCP)](#7-local-execution-no-gcp)
8. [GCP Bootstrap](#8-gcp-bootstrap)
9. [Terraform — Provision Infrastructure](#9-terraform--provision-infrastructure)
10. [Build and Push Docker Images](#10-build-and-push-docker-images)
11. [Run sales_analytics on GCP](#11-run-sales_analytics-on-gcp)
12. [Run churn_prediction on GCP](#12-run-churn_prediction-on-gcp)
13. [Teardown](#13-teardown)

---

## 1. Prerequisites

### GCP

- A GCP project with billing enabled (one per environment: dev, staging, prod)
- `gcloud` CLI installed and authenticated:
  ```bash
  gcloud auth login
  gcloud auth application-default login   # ADC for SDK calls
  gcloud config set project YOUR_PROJECT_ID
  ```
- Docker installed and configured for Artifact Registry:
  ```bash
  gcloud auth configure-docker us-central1-docker.pkg.dev
  ```

### Local

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager — replaces pip/poetry)
- Docker
- Terraform >= 1.5
- Git

---

## 2. Clone and Install

```bash
git clone <repo-url>
cd Sandbox

# Install all dependencies (framework + dev tools)
uv sync

# Verify the CLI is available
uv run gml --help
```

Expected output:
```
Usage: gml [OPTIONS] COMMAND [ARGS]...

Commands:
  compile   Compile pipeline(s) to KFP YAML and/or Airflow DAG files.
  context   Show the resolved context for the current branch.
  deploy    Deploy compiled DAGs, pipeline YAMLs, and feature schemas.
  init      Scaffold a new project or pipeline.
  run       Run a pipeline locally, on Vertex AI, or trigger on Composer.
  teardown  Clean up ephemeral GCP resources for a branch.
```

---

## 3. Understand the Project Structure

```
.
├── framework.yaml                  # Project identity (team, project, GCP config)
├── pyproject.toml                  # Dependencies and build config
├── gcp_ml_framework/              # Framework core (DO NOT EDIT for normal usage)
│   ├── cli/                       # CLI commands (gml run, compile, deploy, ...)
│   ├── components/                # 8 built-in KFP components
│   │   ├── ingestion/             #   BigQueryExtract, GCSExtract
│   │   ├── transformation/        #   BQTransform
│   │   ├── feature_store/         #   WriteFeatures, ReadFeatures
│   │   └── ml/                    #   TrainModel, EvaluateModel, DeployModel
│   ├── pipeline/                  # PipelineBuilder, PipelineCompiler, runners
│   ├── dag/                       # DAGBuilder, DAGCompiler, Airflow task types
│   ├── config.py                  # Layered config (YAML → env vars)
│   ├── context.py                 # MLContext runtime object
│   └── naming.py                  # Canonical GCP resource naming
├── pipelines/                     # Data scientist workspace
│   ├── churn_prediction/          # Pure ML pipeline (PipelineBuilder)
│   │   ├── pipeline.py            #   6-step: ingest → transform → features → train → eval → deploy
│   │   ├── trainer/               #   train.py + requirements.txt (auto-Dockerized)
│   │   ├── seeds/                 #   CSV test data for local runs
│   │   └── config.yaml            #   Pipeline-specific overrides
│   └── sales_analytics/           # Pure ETL DAG (DAGBuilder)
│       ├── dag.py                 #   8-task fan-out/fan-in: 3 extracts → 3 aggs → report → notify
│       ├── sql/                   #   SQL files per task
│       └── seeds/                 #   CSV test data
├── docker/base/                   # Platform-owned base images
│   ├── base-python/Dockerfile     #   python:3.11-slim + build tools
│   ├── base-ml/Dockerfile         #   + ML libs (sklearn, xgboost, lightgbm)
│   └── component-base/Dockerfile  #   + GCP SDKs (bigquery, storage, aiplatform, pyarrow, pandas)
├── terraform/                     # Infrastructure as Code
│   ├── modules/                   #   Reusable modules (composer, iam, storage, artifact_registry)
│   └── envs/                      #   Per-environment configs (dev, staging, prod)
├── scripts/
│   ├── bootstrap.sh               # One-time GCP project setup (APIs, SAs, WIF)
│   └── docker_build.sh            # Auto-generate Dockerfiles and build trainer images
├── tests/                         # 408 tests (unit + integration)
├── dags/                          # Compiled Airflow DAG files (generated)
└── compiled_pipelines/            # Compiled KFP YAML files (generated)
```

### Two pipeline patterns

The platform supports two patterns. Each pipeline directory contains **either**
a `pipeline.py` (ML pipelines on Vertex AI) **or** a `dag.py` (ETL DAGs on
Composer). Never both.

| Pattern | File | Orchestrator | Example |
|---------|------|-------------|---------|
| Pure ML | `pipeline.py` | Vertex AI Pipelines | churn_prediction |
| Pure ETL | `dag.py` | Cloud Composer (Airflow) | sales_analytics |
| Hybrid | `dag.py` + VertexPipelineTask | Composer triggers Vertex | recommendation_engine |

---

## 4. Configure the Project

Edit `framework.yaml` with your GCP project details:

```yaml
team: dsci
project: examplechurn

gcp:
  dev_project_id: YOUR_DEV_PROJECT       # e.g. gcp-gap-demo-dev
  staging_project_id: YOUR_STAGING_PROJECT
  prod_project_id: YOUR_PROD_PROJECT
  region: us-central1
  artifact_registry_host: us-central1-docker.pkg.dev
  composer_dags_path:
    dev: ""       # Populated after Terraform creates Composer
    staging: ""
    prod: ""
```

The `team` and `project` fields drive all resource naming. Every GCP resource
name is derived from the canonical namespace: `{team}-{project}-{branch}`.

---

## 5. Verify Context Resolution

```bash
uv run gml context show
```

Expected output (values depend on your current git branch):

```
  team            dsci
  project         examplechurn
  branch (raw)    os_experimental
  branch (slug)   os-experimental
  git_state       dev
  gcp_project     gcp-gap-demo-dev
  region          us-central1
  namespace       dsci-examplechurn-os-experimental
  gcs_bucket      dsci-examplechurn
  gcs_prefix      gs://dsci-examplechurn/os-experimental/
  bq_dataset      dsci_examplechurn_os_experimen
  feature_store   dsci-examplechurn-os-experimental-fs
```

Key points:
- **git_state**: `dev` for any branch that isn't `main` or `prod/*`
- **bq_dataset**: BQ-safe version of namespace (underscores, max 30 chars)
- **gcs_prefix**: Branch-isolated path within the shared team-project bucket
- **namespace**: The canonical token used in all GCP resource names

---

## 6. Run Tests

```bash
uv run pytest
```

Expected: `408 passed` (all tests run without GCP access).

To run a specific test file:
```bash
uv run pytest tests/unit/test_component_base_image.py -v
```

---

## 7. Local Execution (No GCP)

Local mode uses DuckDB as a BQ substitute and temp files as GCS stubs.
Seed CSV files from `pipelines/<name>/seeds/` are auto-loaded into DuckDB.

### 7a. Run sales_analytics locally

```bash
uv run gml run sales_analytics --local
```

This executes all 8 tasks in topological order against DuckDB. Expected output
includes seeding of raw tables and execution of each SQL task.

To preview the execution plan without running:
```bash
uv run gml run sales_analytics --local --dry-run
```

### 7b. Run churn_prediction locally

```bash
uv run gml run churn_prediction --local
```

This executes the 6-step pipeline sequentially: BigQueryExtract (from DuckDB),
BQTransform (DuckDB SQL), WriteFeatures (log only), TrainModel (placeholder),
EvaluateModel (placeholder metrics), DeployModel (log only).

Local run uses `run_date=2024-01-01` by default (hardcoded in BigQueryExtract's
`local_run()`), which aligns with the seed data dates.

---

## 8. GCP Bootstrap

Run the bootstrap script once per GCP project to enable APIs and create service
accounts:

```bash
./scripts/bootstrap.sh --project YOUR_DEV_PROJECT --env dev
```

This enables:
- `aiplatform.googleapis.com`
- `bigquery.googleapis.com`
- `storage.googleapis.com`
- `secretmanager.googleapis.com`
- `composer.googleapis.com`
- `artifactregistry.googleapis.com`
- `iam.googleapis.com`
- `cloudresourcemanager.googleapis.com`

And creates a service account with roles for BQ, GCS, Vertex AI, Secret Manager,
and Composer.

---

## 9. Terraform — Provision Infrastructure

### 9a. Configure variables

Edit `terraform/envs/dev/terraform.tfvars`:

```hcl
project_id   = "YOUR_DEV_PROJECT"
region       = "us-central1"
team         = "dsci"
project_name = "examplechurn"
environment  = "dev"
github_repo  = ""                  # Set for CI/CD WIF
```

### 9b. Initialize and apply

```bash
cd terraform/envs/dev

# First-time init (downloads providers, configures backend)
terraform init

# Preview what will be created
terraform plan

# Create all resources
terraform apply
```

This provisions:
- **Cloud Composer 3** environment (`dsci-examplechurn-dev`)
- **Artifact Registry** Docker repository (`dsci-examplechurn`)
- **GCS bucket** for pipeline artifacts
- **IAM** service accounts (composer SA, pipeline SA) with required roles

**Note**: Composer 3 creation takes 25-45 minutes on first apply. This is
normal — GKE Autopilot needs to provision the cluster.

**Known issue**: The first `terraform apply` may fail with an IAM race condition
(Composer checks for `roles/composer.worker` before the binding propagates).
Simply re-run `terraform apply` — idempotent, only the Composer resource retries.

### 9c. Update framework.yaml with Composer DAGs path

After Terraform completes, get the Composer DAGs bucket:

```bash
terraform output composer_dags_path
# Example: gs://us-central1-dsci-examplechu-8f740abc-bucket/dags
```

Update `framework.yaml`:
```yaml
gcp:
  composer_dags_path:
    dev: "gs://us-central1-dsci-examplechu-8f740abc-bucket/dags"
```

---

## 10. Build and Push Docker Images

The platform uses a three-tier Docker image hierarchy:

```
base-python          (python:3.11-slim + build tools)
  +-- component-base (+ GCP SDKs, pyarrow, pandas — for KFP components)
  +-- base-ml        (+ sklearn, xgboost, lightgbm — for trainer images)
        +-- churn-prediction-trainer (+ pipeline-specific requirements.txt)
```

### 10a. Authenticate Docker to Artifact Registry

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### 10b. Set environment variables

```bash
export AR_HOST=us-central1-docker.pkg.dev
export GCP_PROJECT=YOUR_DEV_PROJECT
export AR_REPO=dsci-examplechurn          # {team}-{project} from framework.yaml
```

### 10c. Build and push base-python

```bash
docker build -t base-python:latest \
  -f docker/base/base-python/Dockerfile \
  docker/base/base-python

docker tag base-python:latest \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/base-python:latest

docker push ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/base-python:latest
```

### 10d. Build and push component-base

```bash
docker build -t component-base:latest \
  -f docker/base/component-base/Dockerfile \
  docker/base/component-base

# Tag with both latest and branch-sha for the compiler
BRANCH_SHA=$(git rev-parse --abbrev-ref HEAD | tr '[:upper:]/' '[:lower:]-')-$(git rev-parse --short HEAD)

docker tag component-base:latest \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/component-base:latest
docker tag component-base:latest \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/component-base:${BRANCH_SHA}

docker push ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/component-base:latest
docker push ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/component-base:${BRANCH_SHA}
```

The compiler generates the tag `${BRANCH_SHA}` via `NamingConvention.image_tag()`
— it must match the pushed tag exactly.

### 10e. Build and push base-ml + trainer

```bash
docker build -t base-ml:latest \
  -f docker/base/base-ml/Dockerfile \
  docker/base/base-ml

docker tag base-ml:latest \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/base-ml:latest

docker push ${AR_HOST}/${GCP_PROJECT}/${AR_REPO}/base-ml:latest

# Build trainer image (auto-generated Dockerfile from base-ml + requirements.txt)
IMAGE_TAG=${BRANCH_SHA} ./scripts/docker_build.sh
```

`docker_build.sh` scans `pipelines/*/trainer/` for directories containing
`train.py` + `requirements.txt`, auto-generates a Dockerfile (if none exists),
and builds the image. With `AR_HOST`/`GCP_PROJECT`/`AR_REPO` set, it also
pushes to Artifact Registry.

**Verify images in AR**:
```bash
gcloud artifacts docker images list \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO} \
  --include-tags --format='table(package,tags)'
```

Expected:
```
IMAGE                                           TAGS
.../base-python                                 latest
.../base-ml                                     latest
.../component-base                              latest, os-experimental-d5bd511
.../churn-prediction-trainer                    os-experimental-d5bd511
```

---

## 11. Run sales_analytics on GCP

`sales_analytics` is a DAG-based pipeline (ETL) that runs on Cloud Composer.

### 11a. Seed BigQuery with test data

The seed CSV files need to be loaded into BigQuery before the pipeline runs.
Use `gml run --bq` to execute the DAG's SQL tasks directly against BQ:

```bash
uv run gml run sales_analytics --bq --run-date 2026-03-01
```

Or manually load seeds via `bq load`:
```bash
BQ_DATASET=dsci_examplechurn_os_experimen

bq mk --dataset ${GCP_PROJECT}:${BQ_DATASET}

bq load --source_format=CSV --autodetect \
  ${BQ_DATASET}.raw_orders \
  pipelines/sales_analytics/seeds/raw_orders.csv

bq load --source_format=CSV --autodetect \
  ${BQ_DATASET}.raw_inventory \
  pipelines/sales_analytics/seeds/raw_inventory.csv

bq load --source_format=CSV --autodetect \
  ${BQ_DATASET}.raw_returns \
  pipelines/sales_analytics/seeds/raw_returns.csv
```

### 11b. Compile and deploy the DAG

```bash
# Compile: generates Airflow DAG file + any needed KFP YAMLs
uv run gml compile sales_analytics

# Deploy: uploads compiled DAG to Composer's GCS bucket
uv run gml deploy sales_analytics
```

The compiled DAG file lands in `dags/` locally and is uploaded to the Composer
DAGs bucket specified in `framework.yaml`.

**Important**: In DEV, the DAG is compiled with `schedule=None` (manual trigger
only). This prevents auto-scheduled runs from consuming stale seed data.

### 11c. Trigger the DAG on Composer

```bash
uv run gml run sales_analytics --composer --run-date 2026-03-01
```

This triggers the DAG via the Airflow REST API and prints the Airflow UI link
for monitoring.

**Expected results** (8 tasks):
- 3 parallel extract tasks → 3 aggregation tasks → 1 report → 1 notify
- 7/8 tasks SUCCESS (notify fails in DEV — no SMTP configured)
- `daily_report` BQ table: 3 rows (Clothing, Electronics, Home)

**Note**: First trigger on a cold Composer 3 environment may take 15-20 minutes
for GKE Autopilot to scale workers. Subsequent triggers execute immediately.

---

## 12. Run churn_prediction on GCP

`churn_prediction` is a pure ML pipeline (PipelineBuilder) that runs on
Vertex AI Pipelines.

### 12a. Seed BigQuery with test data

```bash
BQ_DATASET=dsci_examplechurn_os_experimen

bq load --source_format=CSV --autodetect \
  ${BQ_DATASET}.raw_user_events \
  pipelines/churn_prediction/seeds/raw_user_events.csv
```

Verify the data:
```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as rows, MIN(event_date) as min_date, MAX(event_date) as max_date
   FROM ${BQ_DATASET}.raw_user_events"
```

Expected: 10 rows, dates from 2023-10-15 to 2023-12-23.

### 12b. Ensure Docker images are pushed

The pipeline requires two images in Artifact Registry:
1. **component-base** — used by all KFP components (bigquery-extract, bq-transform,
   write-features, evaluate-model, deploy-model)
2. **churn-prediction-trainer** — used by the train-model step

Verify with:
```bash
gcloud artifacts docker images list \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO} \
  --include-tags
```

If missing, follow [Step 10](#10-build-and-push-docker-images).

### 12c. Compile the pipeline

```bash
uv run gml compile churn_prediction
```

This generates `compiled_pipelines/churn_prediction.yaml` (KFP v2 YAML) and
`dags/dsci_examplechurn_os_experimen__churn_prediction.py` (auto-wrapped DAG
for Composer).

**Verify the compiled YAML uses component-base** (not python:3.11-slim):
```bash
grep -c "component-base" compiled_pipelines/churn_prediction.yaml
# Expected: 6 (one per step)

grep -c "python:3.11-slim" compiled_pipelines/churn_prediction.yaml
# Expected: 0
```

### 12d. Submit to Vertex AI

```bash
uv run gml run churn_prediction --vertex --sync --run-date 2024-01-01
```

Flags:
- `--vertex` — submit to Vertex AI Pipelines (not local, not Composer)
- `--sync` — block until the pipeline completes (or fails)
- `--run-date 2024-01-01` — sets the logical date. Must be within 90 days of
  the seed data (Oct-Dec 2023). If omitted, defaults to today's date, which
  will produce 0 rows from the seed data.

The CLI:
1. Compiles the pipeline to KFP YAML
2. Submits to Vertex AI via `aiplatform.PipelineJob`
3. Prints the Vertex AI console URL for monitoring
4. With `--sync`, waits for completion

**Expected timeline** (~7-8 minutes for the 5 compute steps + ~20 min for deploy):

| Step | What it does | Duration |
|------|-------------|----------|
| bigquery-extract | Query `raw_user_events` → write to `churn_training_raw` → export Parquet | ~30-80s |
| bq-transform | Feature engineering SQL → `churn_features_engineered` | ~30-40s |
| write-features | Register `churn_features_engineered` as Feature Store FeatureGroup | ~40-50s |
| train-model | Vertex Custom Training Job (sklearn LogisticRegression) | ~3-5 min |
| evaluate-model | Load model from GCS, compute AUC/F1 on eval data, apply gate | ~60s |
| deploy-model | Upload model to Vertex Model Registry, deploy to endpoint | ~15-20 min |

**Total**: ~25-30 minutes (dominated by deploy-model's endpoint provisioning).

### 12e. Monitor the pipeline

The CLI prints a console URL:
```
View Pipeline Job:
https://console.cloud.google.com/vertex-ai/locations/us-central1/pipelines/runs/churn-prediction-YYYYMMDDHHMMSS?project=PROJECT_NUMBER
```

Or check programmatically:
```python
from google.cloud import aiplatform
aiplatform.init(project="YOUR_PROJECT", location="us-central1")
job = aiplatform.PipelineJob.get("projects/PROJECT_NUMBER/locations/us-central1/pipelineJobs/JOB_ID")
for task in job.gca_resource.job_detail.task_details:
    print(f"{task.task_name}: {task.state.name}")
```

### 12f. Verify results

After successful completion:

**BigQuery tables**:
```bash
bq query --use_legacy_sql=false \
  "SELECT table_id, row_count FROM \`${BQ_DATASET}.__TABLES__\`
   WHERE table_id IN ('churn_training_raw', 'churn_features_engineered')
   ORDER BY table_id"
```

Both should have 10 rows (matching the seed data).

**Model in GCS**:
```bash
gsutil ls gs://dsci-examplechurn/os-experimental/models/churn_prediction/latest/
# Expected: model.pkl
```

**Vertex AI Endpoint** (if deploy-model succeeded):
```bash
gcloud ai endpoints list --region=us-central1 --project=YOUR_PROJECT
```

### 12g. Re-runs and caching

Vertex AI caches step outputs by default. On re-submission with the same
parameters, completed steps are SKIPPED (cached) and only changed/failed steps
re-execute. To force a full re-run:

```bash
uv run gml run churn_prediction --vertex --sync --run-date 2024-01-01 --no-cache
```

---

## 13. Teardown

### Remove ephemeral GCP resources for a branch

```bash
uv run gml teardown --branch os_experimental
```

This cleans up branch-namespaced resources (BQ datasets, GCS prefixes, Vertex
experiments, endpoints, models).

### Destroy Terraform infrastructure

```bash
cd terraform/envs/dev
terraform destroy
```

This removes Composer, Artifact Registry, GCS bucket, and IAM resources.

**Warning**: Composer destruction takes 10-15 minutes. AR destruction will
fail if images still exist — delete images first or use `--force`.

### Undeploy the Vertex AI endpoint (avoid ongoing charges)

Deployed endpoints incur per-hour charges for provisioned VMs. To undeploy:

```bash
gcloud ai endpoints undeploy-model ENDPOINT_ID \
  --deployed-model-id=DEPLOYED_MODEL_ID \
  --region=us-central1 \
  --project=YOUR_PROJECT
```

Or delete the endpoint entirely:
```bash
gcloud ai endpoints delete ENDPOINT_ID \
  --region=us-central1 \
  --project=YOUR_PROJECT
```

---

## Appendix A: Common Issues

### "No module named 'sklearn'" in evaluate-model

The component-base image does not include ML libraries. The evaluate_model
component installs `scikit-learn` at runtime (~15s overhead). This is by design —
only one step needs it, and adding it to component-base would bloat the image
for the other 5 steps that don't need it.

### Empty training data (0 rows)

The BigQueryExtract query uses a 90-day date window relative to `run_date`.
If `run_date` doesn't align with the data in the source table, 0 rows are
returned. For the seed data (Oct-Dec 2023), use `--run-date 2024-01-01`.

### Terraform IAM race condition

First `terraform apply` may fail with a Composer IAM error. Re-run
`terraform apply` — it's idempotent.

### Composer cold-start latency

First DAG trigger on a SMALL Composer 3 environment takes 15-20 minutes
(GKE Autopilot worker provisioning). Subsequent triggers are fast.

### Image tag mismatch

The compiler generates image tags as `{branch}-{short_sha}` via
`NamingConvention.image_tag()`. If you push images with a different tag,
the pipeline will fail with an image pull error. Always verify:

```bash
# What the compiler expects
uv run python -c "
from gcp_ml_framework.naming import NamingConvention
n = NamingConvention(team='dsci', project='examplechurn')
print(n.image_tag())
"

# What AR has
gcloud artifacts docker images list \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO} --include-tags
```

---

## Appendix B: CLI Reference

| Command | Description |
|---------|------------|
| `gml context show` | Display resolved namespace and resource names |
| `gml compile <name>` | Compile pipeline to KFP YAML and/or Airflow DAG |
| `gml compile --all` | Compile all pipelines |
| `gml deploy <name>` | Compile + upload artifacts to GCS/Composer |
| `gml run <name> --local` | Execute locally with DuckDB stubs |
| `gml run <name> --local --dry-run` | Preview execution plan |
| `gml run <name> --vertex` | Submit to Vertex AI Pipelines |
| `gml run <name> --vertex --sync` | Submit and wait for completion |
| `gml run <name> --vertex --no-cache` | Submit with step caching disabled |
| `gml run <name> --composer` | Trigger DAG on Cloud Composer |
| `gml run <name> --bq` | Execute DAG SQL directly on BigQuery |
| `gml teardown --branch <name>` | Clean up branch resources |
| `gml init project` | Scaffold a new project |
| `gml init pipeline <name>` | Scaffold a new pipeline |

All commands accept `--run-date YYYY-MM-DD` to override the logical date
(defaults to today).

---

## Appendix C: Docker Image Hierarchy

```
python:3.11-slim                              (upstream, ~150 MB)
  └── base-python:latest                      (+ build-essential, curl)
        ├── component-base:{branch}-{sha}     (+ GCP SDKs, pyarrow, pandas, db-dtypes)
        │     Used by: bigquery-extract, bq-transform, write-features,
        │              evaluate-model, deploy-model
        │
        └── base-ml:latest                    (+ numpy, sklearn, xgboost, lightgbm)
              └── churn-prediction-trainer:{branch}-{sha}
                    (+ pipeline-specific requirements.txt)
                    Used by: train-model (Vertex Custom Training Job)
```

**Why two branches?**
- Most KFP steps only need GCP SDKs — they query BQ, read/write GCS, call
  Vertex APIs. Adding ML libraries would double the image size for no benefit.
- Trainer images need ML libraries but NOT GCP component SDKs (the training
  script uses BQ/GCS clients directly from its own requirements.txt).
- `evaluate-model` is the one exception: it uses component-base for GCP SDKs
  and pip-installs `scikit-learn` at runtime (~15s). This avoids maintaining a
  third base image for a single step.

---

## Appendix D: Resource Naming

All GCP resources are derived from `{team}-{project}-{branch}`:

| Resource | Naming Pattern | Example |
|----------|---------------|---------|
| Namespace | `{team}-{project}-{branch}` | `dsci-examplechurn-os-experimental` |
| BQ dataset | `{namespace_bq}` (underscored, 30 chars) | `dsci_examplechurn_os_experimen` |
| GCS bucket | `{team}-{project}` (shared) | `dsci-examplechurn` |
| GCS prefix | `gs://{bucket}/{branch}/` | `gs://dsci-examplechurn/os-experimental/` |
| AR repo | `{team}-{project}` | `dsci-examplechurn` |
| Image tag | `{branch}-{sha}` | `os-experimental-d5bd511` |
| Vertex pipeline | `{namespace}-{pipeline}` | `dsci-examplechurn-os-experimental-churn-prediction` |
| Vertex experiment | `{namespace}-{pipeline}-exp` | `dsci-examplechurn-os-experimental-churn-prediction-exp` |
| Vertex endpoint | `{namespace}-{endpoint_name}` | `dsci-examplechurn-os-experimental-churn-classifier` |
| DAG ID | `{namespace_bq}__{pipeline}` | `dsci_examplechurn_os_experimen__sales_analytics` |
| Feature Store | `{namespace}-fs` | `dsci-examplechurn-os-experimental-fs` |
