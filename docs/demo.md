# End-to-End Demo -- GCP ML/Data Orchestration Platform

> Step-by-step walkthrough: from a clean clone to verified GCP execution of all
> three pipelines (sales_analytics, churn_prediction, recommendation_engine).
>
> Audience: New team members, reviewers, demo presenters.
>
> Last updated: 2026-03-11 (v3)

---

## Table of Contents

1.  [Prerequisites](#1-prerequisites)
2.  [Clone and Install](#2-clone-and-install)
3.  [Project Structure](#3-project-structure)
4.  [Configure framework.yaml](#4-configure-frameworkyaml)
5.  [Verify Context Resolution](#5-verify-context-resolution)
6.  [Run Tests](#6-run-tests)
7.  [Local Execution (No GCP)](#7-local-execution-no-gcp)
8.  [GCP Bootstrap (One-Time)](#8-gcp-bootstrap-one-time)
9.  [Terraform -- Provision Infrastructure](#9-terraform----provision-infrastructure)
10. [Post-Terraform Configuration](#10-post-terraform-configuration)
11. [Build and Push Docker Images](#11-build-and-push-docker-images)
12. [Seed BigQuery with Test Data](#12-seed-bigquery-with-test-data)
13. [Compile Pipelines](#13-compile-pipelines)
14. [Deploy to GCP](#14-deploy-to-gcp)
15. [Run sales_analytics on Composer](#15-run-sales_analytics-on-composer)
16. [Run churn_prediction on Vertex AI](#16-run-churn_prediction-on-vertex-ai)
17. [Run churn_prediction via Composer](#17-run-churn_prediction-via-composer)
18. [Run recommendation_engine on Composer + Vertex AI](#18-run-recommendation_engine-on-composer--vertex-ai)
19. [Verify Results](#19-verify-results)
20. [Teardown](#20-teardown)
21. [Appendix A: CLI Reference](#appendix-a-cli-reference)
22. [Appendix B: Docker Image Hierarchy](#appendix-b-docker-image-hierarchy)
23. [Appendix C: Resource Naming](#appendix-c-resource-naming)
24. [Appendix D: Run-Date Alignment](#appendix-d-run-date-alignment)
25. [Appendix E: Common Issues](#appendix-e-common-issues)

---

## 1. Prerequisites

### GCP Account

- A GCP project with billing enabled. For a full multi-environment demo you need
  three projects (dev/staging/prod); for a single-environment demo, one is sufficient.
- `Owner` role (or at minimum the specific roles listed in `docs/prerequisite/infrastructure.md`)
  on the GCP project.

### Local Tooling

| Tool | Version | Install |
|------|---------|---------|
| Python | >= 3.11 | System or pyenv |
| [uv](https://docs.astral.sh/uv/) | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | Latest | [docs.docker.com](https://docs.docker.com/get-docker/) |
| Terraform | >= 1.5 | [developer.hashicorp.com/terraform](https://developer.hashicorp.com/terraform/install) |
| gcloud CLI | Latest | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) |
| Git | Any modern version | System package manager |

### GCP Authentication

Run these once on your local machine:

```bash
# Interactive login (opens browser)
gcloud auth login

# Application Default Credentials -- required for all SDK calls (BQ, GCS, Vertex, etc.)
gcloud auth application-default login

# Set your default project
gcloud config set project YOUR_PROJECT_ID

# Configure Docker to push to Artifact Registry (use YOUR region)
gcloud auth configure-docker YOUR_REGION-docker.pkg.dev
```

Authentication uses ADC (Application Default Credentials) throughout -- no
service account keys, no manual token fetching. This follows GCP best practices.

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

## 3. Project Structure

```
.
+-- framework.yaml                  # Project identity (team, project, GCP config)
+-- pyproject.toml                  # Dependencies and build config
+-- gcp_ml_framework/              # Framework core (DO NOT EDIT for normal usage)
|   +-- cli/                       # CLI commands (gml run, compile, deploy, ...)
|   +-- components/                # 8 built-in KFP v2 components
|   |   +-- ingestion/             #   BigQueryExtract, GCSExtract
|   |   +-- transformation/        #   BQTransform
|   |   +-- feature_store/         #   WriteFeatures, ReadFeatures
|   |   +-- ml/                    #   TrainModel, EvaluateModel, DeployModel
|   +-- pipeline/                  # PipelineBuilder, PipelineCompiler, runners
|   +-- dag/                       # DAGBuilder, DAGCompiler, DAG task types
|   +-- config.py                  # Layered config (YAML -> env vars)
|   +-- context.py                 # MLContext runtime object
|   +-- naming.py                  # Canonical GCP resource naming
|   +-- utils/                     # BQ, GCS, AR, SQL compat utilities
+-- pipelines/                     # Data scientist workspace
|   +-- churn_prediction/          # Pure ML pipeline (PipelineBuilder)
|   |   +-- pipeline.py            #   6-step: ingest -> transform -> features -> train -> eval -> deploy
|   |   +-- trainer/               #   train.py + requirements.txt (auto-Dockerized)
|   |   +-- seeds/                 #   raw_user_events.csv
|   +-- sales_analytics/           # Pure ETL DAG (DAGBuilder)
|   |   +-- dag.py                 #   8-task fan-out/fan-in: 3 extracts -> 3 aggs -> report -> notify
|   |   +-- sql/                   #   SQL files per task
|   |   +-- seeds/                 #   raw_orders.csv, raw_inventory.csv, raw_returns.csv
|   +-- recommendation_engine/     # Hybrid DAG (DAGBuilder + 2 VertexPipelineTasks)
|       +-- dag.py                 #   extract -> Vertex Pipeline 1 (features) -> Vertex Pipeline 2 (train) -> notify
|       +-- sql/                   #   extract_interactions.sql
|       +-- trainer/               #   NMF recommendation model trainer
|       +-- seeds/                 #   raw_interactions.csv
+-- docker/base/                   # Platform-owned base images
|   +-- base-python/Dockerfile     #   python:3.11-slim + build tools
|   +-- base-ml/Dockerfile         #   + ML libs (sklearn, xgboost, lightgbm)
|   +-- component-base/Dockerfile  #   + GCP SDKs (bigquery, storage, aiplatform, pyarrow, pandas)
+-- terraform/                     # Infrastructure as Code
|   +-- modules/                   #   Reusable modules (composer, iam, storage, artifact_registry)
|   +-- envs/                      #   Per-environment configs (dev, staging, prod)
+-- scripts/
|   +-- bootstrap.sh               # One-time GCP project setup (APIs, AR repo)
|   +-- docker_build.sh            # Build full Docker image hierarchy and optionally push
|   +-- seed_bq.sh                 # Load seed CSVs into BigQuery
+-- tests/                         # 451+ tests (unit + integration)
+-- dags/                          # Compiled Airflow DAG files (generated output)
+-- compiled_pipelines/            # Compiled KFP YAML files (generated output)
```

### Three Pipeline Patterns

| Pattern | File | Orchestrator | Example |
|---------|------|-------------|---------|
| Pure ML | `pipeline.py` | Vertex AI Pipelines (auto-wrapped in Composer DAG) | churn_prediction |
| Pure ETL | `dag.py` | Cloud Composer (native Airflow operators) | sales_analytics |
| Hybrid | `dag.py` with VertexPipelineTask(s) | Composer orchestrates Vertex AI | recommendation_engine |

---

## 4. Configure framework.yaml

`framework.yaml` is the single source of truth for project identity and GCP configuration.

```yaml
# GCP ML Framework -- project configuration
team: dsci
project: gcpdemo

gcp:
  dev_project_id: prj-0n-dta-pt-ai-sandbox    # your GCP project ID
  staging_project_id: ""                        # leave blank until multi-env
  prod_project_id: ""
  region: us-east4

  # Service account for Vertex AI pipeline execution
  service_account_email: gc-sa-for-vertex-ai-pipelines@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com

  # Composer environment name (if using a pre-existing shared environment)
  composer_environment_name: mlopshousingpoc

  # Composer DAGs bucket path (populated after Terraform or from existing env)
  composer_dags_path:
    dev: "gs://us-east4-mlopshousingpoc-030c6745-bucket/dags"
    staging: ""
    prod: ""
  # artifact_registry_host auto-derived from region -> us-east4-docker.pkg.dev
```

The `team` and `project` fields drive all resource naming. Every GCP resource
name is derived from the canonical namespace: `{team}-{project}-{branch}`.

Key fields:

| Field | Purpose | Example |
|-------|---------|---------|
| `team` | Team identifier (max 12 chars) | `dsci` |
| `project` | Framework project name (max 20 chars) | `gcpdemo` |
| `dev_project_id` | GCP project for DEV branches | `prj-0n-dta-pt-ai-sandbox` |
| `region` | GCP region for all resources | `us-east4` |
| `service_account_email` | SA used by Vertex AI pipelines | Pre-existing or TF-created |
| `composer_environment_name` | Composer env name (if shared/pre-existing) | `mlopshousingpoc` |
| `composer_dags_path` | GCS path where Composer reads DAGs | From Composer env details |

**Do not put secrets here.** Secrets go in GCP Secret Manager and are referenced
via `!secret key-name` in config.

---

## 5. Verify Context Resolution

```bash
uv run gml context show
```

Expected output (values depend on your current git branch):

```
  team            dsci
  project         gcpdemo
  branch (raw)    test
  branch (slug)   test
  git_state       dev
  gcp_project     prj-0n-dta-pt-ai-sandbox
  region          us-east4
  namespace       dsci-gcpdemo-test
  gcs_bucket      prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo
  gcs_prefix      gs://prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo/test/
  bq_dataset      dsci_gcpdemo_test
```

Key concepts:

- **git_state**: `dev` for any feature branch, `staging` for `main`, `prod` for `v*` tags
- **namespace**: The canonical token used in ALL GCP resource names
- **bq_dataset**: BQ-safe name (underscores, max 30 chars)
- **gcs_prefix**: Branch-isolated path within a shared project bucket

Use `--json` for machine-readable output, or `--branch <name>` to inspect a
different branch without checking it out.

---

## 6. Run Tests

```bash
uv run pytest
```

Expected: `451+ passed`. All tests run without GCP access -- they use mocks and
DuckDB stubs.

To run a specific test file:

```bash
uv run pytest tests/unit/test_dag_compiler.py -v
```

---

## 7. Local Execution (No GCP)

Local mode uses DuckDB as a BigQuery substitute and temp directories for GCS stubs.
Seed CSV files from `pipelines/<name>/seeds/` are auto-loaded into DuckDB.

### 7a. sales_analytics (pure ETL)

```bash
uv run gml run sales_analytics --local
```

Executes all 8 tasks in topological order against DuckDB:
3 parallel extracts -> 3 aggregations -> build_report -> notify (printed to console).

Preview the execution plan without running:

```bash
uv run gml run sales_analytics --local --dry-run
```

### 7b. recommendation_engine (hybrid)

```bash
uv run gml run recommendation_engine --local
```

Executes the DAG locally, including the two nested Vertex pipelines (which run
via the pipeline LocalRunner recursively against DuckDB).

### 7c. churn_prediction (pure ML)

```bash
uv run gml run churn_prediction --local --run-date 2024-01-01
```

All 6 steps succeed: ingest -> transform -> write features -> train (real sklearn
model on seed data) -> evaluate (AUC=1.0, F1=1.0 on small seed set -- gate 0.78
passes) -> deploy (stub).

> **Note on `--run-date`**: The seed data covers Oct-Dec 2023. The pipeline's
> BigQuery query uses a 90-day lookback from `run_date`. With `2024-01-01`, all
> seed rows are captured. Without `--run-date`, it defaults to today and returns
> 0 rows.

### 7d. Override run date

All local runs accept `--run-date` to set the logical date:

```bash
uv run gml run sales_analytics --local --run-date 2026-03-01
```

---

## 8. GCP Bootstrap (One-Time)

The bootstrap script enables required GCP APIs and creates the Artifact Registry
repository. Service accounts and IAM are managed separately (either by Terraform
or pre-existing in your enterprise environment).

```bash
./scripts/bootstrap.sh --project YOUR_PROJECT_ID --region YOUR_REGION
```

Example with the current project:

```bash
./scripts/bootstrap.sh --project prj-0n-dta-pt-ai-sandbox --region us-east4
```

This enables:

| API | Purpose |
|-----|---------|
| `aiplatform.googleapis.com` | Vertex AI (pipelines, training, endpoints) |
| `bigquery.googleapis.com` | Data warehouse |
| `storage.googleapis.com` | Object storage (pipeline artifacts, models) |
| `secretmanager.googleapis.com` | Secret management |
| `composer.googleapis.com` | Cloud Composer (Airflow orchestration) |
| `artifactregistry.googleapis.com` | Docker image registry |
| `iam.googleapis.com` | Identity and access management |
| `cloudresourcemanager.googleapis.com` | Project resource management |
| `compute.googleapis.com` | Required by Composer 3 (GKE Autopilot) |

The script also creates the Artifact Registry Docker repository
(`{team}-{project}` from `framework.yaml`, e.g., `dsci-gcpdemo`).

---

## 9. Terraform -- Provision Infrastructure

Terraform provisions shared infrastructure. There are two deployment scenarios
depending on your environment.

### Scenario A: Greenfield (You Own the Project)

Terraform creates everything: Composer 3, Artifact Registry, GCS bucket, IAM
service accounts, and optionally WIF. This is the full-control path.

**All 4 modules are used**: `storage`, `artifact_registry`, `iam`, `composer`.

See the `staging` and `prod` environment configs for examples of this approach.

### Scenario B: Enterprise / Shared Environment

In enterprise setups, some resources are pre-existing and managed outside your
control (e.g., shared Composer environments, pre-provisioned service accounts).
Terraform only manages what you own.

This is the current DEV setup for `prj-0n-dta-pt-ai-sandbox`:
- **Pre-existing**: Composer env (`mlopshousingpoc`), Pipeline SA, Composer SA
- **TF-managed**: GCS bucket, Artifact Registry repo
- **Skipped modules**: `iam`, `composer` (commented out in `terraform/envs/dev/main.tf`)

### 9a. Configure variables

Edit `terraform/envs/dev/terraform.tfvars`:

```hcl
project_id   = "prj-0n-dta-pt-ai-sandbox"
region       = "us-east4"
team         = "dsci"                    # must match framework.yaml
project_name = "gcpdemo"                 # must match framework.yaml
environment  = "dev"
```

### 9b. (Optional) Configure remote state backend

For persistent state, use a GCS backend. Create the bucket first:

```bash
gsutil mb -p YOUR_PROJECT_ID -l YOUR_REGION gs://YOUR-PROJECT-terraform-state/
gsutil versioning set on gs://YOUR-PROJECT-terraform-state/
```

Then update the `backend "gcs"` block in `terraform/envs/dev/main.tf` to point
to your state bucket. For local-only demos, you can use a local backend instead.

### 9c. Initialize and apply

```bash
cd terraform/envs/dev

# Download providers and configure backend
terraform init

# Preview what will be created
terraform plan

# Create resources
terraform apply
```

### What Terraform creates (varies by scenario)

| Resource | Greenfield | Enterprise |
|----------|-----------|-----------|
| **GCS bucket** | `{project_id}-{team}-{project}` (versioning enabled) | Same |
| **Artifact Registry** | `{team}-{project}` Docker repo | Same |
| **Composer SA** | `{team}-{project}-{env}-composer@...` | Pre-existing (skipped) |
| **Pipeline SA** | `{team}-{project}-{env}-pipeline@...` | Pre-existing (skipped) |
| **Cloud Composer 3** | Sized per env (SMALL/MEDIUM) | Pre-existing (skipped) |
| **WIF** (optional) | GitHub Actions OIDC pool + provider | N/A |

### Known issue: IAM race condition (greenfield only)

The first `terraform apply` may fail with:

```
Composer create failed: ...composer@... is expected to have at least one role like roles/composer.worker
```

This is a GCP eventual-consistency issue. Simply re-run `terraform apply` -- it's
idempotent and only the Composer resource will retry.

---

## 10. Post-Terraform Configuration

After infrastructure is provisioned (or if using pre-existing resources), update
`framework.yaml` with the correct values.

### 10a. Get the Composer DAGs bucket path

**If Terraform created Composer:**

```bash
cd terraform/envs/dev
terraform output composer_dags_path
```

**If using a pre-existing Composer environment:**

```bash
gcloud composer environments describe YOUR_COMPOSER_ENV_NAME \
  --location YOUR_REGION \
  --format='value(config.dagGcsPrefix)'
```

Example for the current setup:

```bash
gcloud composer environments describe mlopshousingpoc \
  --location us-east4 \
  --format='value(config.dagGcsPrefix)'
# Output: gs://us-east4-mlopshousingpoc-030c6745-bucket/dags
```

### 10b. Get the Pipeline service account email

**If Terraform created SAs:**

```bash
terraform output pipeline_service_account
```

**If using pre-existing SAs:**

```bash
gcloud iam service-accounts list --project=YOUR_PROJECT_ID \
  --filter="displayName~pipeline OR displayName~vertex" \
  --format="table(email,displayName)"
```

### 10c. Update framework.yaml

Fill in all resolved values:

```yaml
gcp:
  service_account_email: gc-sa-for-vertex-ai-pipelines@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com
  composer_environment_name: mlopshousingpoc
  composer_dags_path:
    dev: "gs://us-east4-mlopshousingpoc-030c6745-bucket/dags"
```

### 10d. Configure Docker auth

```bash
gcloud auth configure-docker us-east4-docker.pkg.dev
```

Replace `us-east4` with your region.

---

## 11. Build and Push Docker Images

The platform uses a three-tier Docker image hierarchy. Two of the three
pipelines (churn_prediction and recommendation_engine) have `trainer/`
directories that require Docker images. All KFP components use the
`component-base` image.

### 11a. Set environment variables

```bash
export AR_HOST=us-east4-docker.pkg.dev
export GCP_PROJECT=prj-0n-dta-pt-ai-sandbox
export AR_REPO=dsci-gcpdemo                                    # = {team}-{project} from framework.yaml
export BRANCH_SHA=$(git rev-parse --abbrev-ref HEAD | tr '[:upper:]/' '[:lower:]-')-$(git rev-parse --short HEAD)
```

The `BRANCH_SHA` variable (e.g., `test-a88424d`) is the tag the compiler embeds
in pipeline YAMLs. It **must** match the pushed image tag.

### 11b. Build and push all images

`docker_build.sh` builds the full image hierarchy in dependency order and pushes
to Artifact Registry with `--push`:

```bash
export IMAGE_TAG=${BRANCH_SHA}
./scripts/docker_build.sh --push
```

Build order:
1. **base-python** -- `python:3.11-slim` + build tools (foundation for all images)
2. **base-ml** -- + ML libs (sklearn, xgboost, lightgbm) -- base for trainer images
3. **component-base** -- + GCP SDKs (bigquery, storage, aiplatform) -- base for KFP components
4. **trainer images** -- auto-generated per `pipelines/*/trainer/` (train.py + requirements.txt)

All images are tagged with `IMAGE_TAG` (e.g., `test-a88424d`).

Without `--push`, the script builds locally only. Without AR env vars, images
are tagged locally (e.g., `base-python:test-a88424d`).

### 11c. Verify images in Artifact Registry

```bash
gcloud artifacts docker images list \
  ${AR_HOST}/${GCP_PROJECT}/${AR_REPO} \
  --include-tags --format='table(package,tags)'
```

Expected:

```
IMAGE                                    TAGS
.../base-python                          test-a88424d
.../base-ml                              test-a88424d
.../component-base                       test-a88424d
.../churn-prediction-trainer             test-a88424d
.../recommendation-engine-trainer        test-a88424d
```

---

## 12. Seed BigQuery with Test Data

Pipeline SQL queries filter by date, so the seed data and `--run-date` must align.
The `scripts/seed_bq.sh` script loads all CSV seed files from `pipelines/*/seeds/`.

### 12a. Automated seeding (recommended)

```bash
./scripts/seed_bq.sh
```

This script:
1. Reads `framework.yaml` + current git branch to resolve the BQ dataset and project
2. Creates the BQ dataset if it doesn't exist
3. Loads all `pipelines/*/seeds/*.csv` files into the dataset

It auto-detects all seed files:

| Pipeline | Seed File | BQ Table |
|----------|-----------|----------|
| churn_prediction | `seeds/raw_user_events.csv` | `raw_user_events` |
| sales_analytics | `seeds/raw_orders.csv` | `raw_orders` |
| sales_analytics | `seeds/raw_inventory.csv` | `raw_inventory` |
| sales_analytics | `seeds/raw_returns.csv` | `raw_returns` |
| recommendation_engine | `seeds/raw_interactions.csv` | `raw_interactions` |

### 12b. Manual seeding (alternative)

```bash
BQ_DATASET=$(uv run gml context show --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['bq_dataset'])")
GCP_PROJECT=$(uv run gml context show --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['gcp_project'])")
BQ_LOCATION=$(uv run gml context show --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['region'])")

# churn_prediction
bq load --project_id=${GCP_PROJECT} --location=${BQ_LOCATION} \
  --source_format=CSV --autodetect --replace \
  ${BQ_DATASET}.raw_user_events \
  pipelines/churn_prediction/seeds/raw_user_events.csv

# sales_analytics
for table in raw_orders raw_inventory raw_returns; do
  bq load --project_id=${GCP_PROJECT} --location=${BQ_LOCATION} \
    --source_format=CSV --autodetect --replace \
    ${BQ_DATASET}.${table} \
    pipelines/sales_analytics/seeds/${table}.csv
done

# recommendation_engine
bq load --project_id=${GCP_PROJECT} --location=${BQ_LOCATION} \
  --source_format=CSV --autodetect --replace \
  ${BQ_DATASET}.raw_interactions \
  pipelines/recommendation_engine/seeds/raw_interactions.csv
```

### 12c. Verify seed data

```bash
bq query --project_id=${GCP_PROJECT} --use_legacy_sql=false \
  "SELECT table_id, row_count FROM \`${BQ_DATASET}.__TABLES__\` ORDER BY table_id"
```

---

## 13. Compile Pipelines

Compilation generates Airflow DAG files and KFP v2 YAML files from the pipeline
definitions. This is a local operation -- no GCP access needed.

### 13a. Compile all pipelines

```bash
uv run gml compile --all
```

### 13b. Compile individually

```bash
uv run gml compile churn_prediction
uv run gml compile sales_analytics
uv run gml compile recommendation_engine
```

### What gets generated

| Pipeline | Generated Files |
|----------|----------------|
| churn_prediction | `compiled_pipelines/churn_prediction.yaml` (KFP v2), `dags/{ns}__churn_prediction.py` (Airflow DAG with RunPipelineJobOperator) |
| sales_analytics | `dags/{ns}__sales_analytics.py` (Airflow DAG with BigQueryInsertJobOperator tasks) |
| recommendation_engine | `compiled_pipelines/reco_features.yaml`, `compiled_pipelines/reco_training.yaml` (2 KFP v2), `dags/{ns}__recommendation_engine.py` (Airflow DAG with 2 RunPipelineJobOperators) |

Where `{ns}` is the BQ namespace, e.g., `dsci_gcpdemo_test`.

### 13c. Verify compilation

Check that component-base is used (not python:3.11-slim):

```bash
grep -c "component-base" compiled_pipelines/churn_prediction.yaml
# Expected: > 0

grep -c "python:3.11-slim" compiled_pipelines/churn_prediction.yaml
# Expected: 0
```

Check that generated DAGs have zero framework imports:

```bash
grep -r "gcp_ml_framework" dags/
# Expected: no output (only comments mentioning the source)
```

---

## 14. Deploy to GCP

`gml deploy` compiles (if needed), verifies Docker images in AR, uploads DAG
files to Composer, and uploads pipeline YAMLs to GCS.

### 14a. Deploy all

```bash
uv run gml deploy --all
```

### 14b. Deploy individually

```bash
uv run gml deploy churn_prediction
uv run gml deploy sales_analytics
uv run gml deploy recommendation_engine
```

### 14c. Preview without deploying

```bash
uv run gml deploy --all --dry-run
```

### What deploy does (5 steps)

1. **Compile** -- runs `gml compile` to generate/refresh artifacts
2. **Verify images** -- scans compiled YAML for AR image URIs, verifies each
   exists in Artifact Registry. If a tag is missing but the same image exists
   with a branch-matching tag, it auto-retags via `gcloud artifacts docker tags add`
3. **Upload DAGs** -- copies generated DAG `.py` files to the Composer GCS
   bucket (`composer_dags_path` from `framework.yaml`)
4. **Upload pipeline YAMLs** -- copies compiled KFP YAMLs to GCS at
   `gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml`
5. **Deploy features** (with `--all`) -- syncs feature schemas from
   `feature_schemas/` to Feature Store

### Important: Composer DAG parsing delay

After deploying, Composer 3 needs approximately **5 minutes** to parse new DAG
files. Wait for the DAG to appear in the Airflow UI before triggering.

---

## 15. Run sales_analytics on Composer

`sales_analytics` is a pure ETL DAG -- 8 BQ/email tasks, no Vertex AI, no Docker.

### 15a. Trigger the DAG

```bash
uv run gml run sales_analytics --composer --run-date 2026-03-01
```

The `--run-date` must align with the seed data dates. For sales_analytics, the
seed data uses dates around `2026-03-01`.

This command:
1. Resolves the DAG ID: `{namespace_bq}__sales_analytics`
2. Unpauses the DAG (Composer 3 defaults new DAGs to paused)
3. Triggers via the Airflow REST API
4. Prints the Airflow UI link for monitoring

### 15b. Expected results

- 7/8 tasks SUCCESS (notify fails in DEV -- no SMTP configured; this is expected)
- `daily_report` BQ table: 3 rows (Clothing, Electronics, Home) with correct
  revenue, refund, and stock figures

### 15c. Cold-start warning

First trigger on a cold Composer 3 (SMALL) environment takes **15-20 minutes**
for GKE Autopilot to provision workers. Subsequent triggers execute within 4-5
minutes.

---

## 16. Run churn_prediction on Vertex AI

`churn_prediction` can be submitted directly to Vertex AI (bypassing Composer).
This is the fastest way to validate the ML pipeline.

### 16a. Direct Vertex AI submission

```bash
uv run gml run churn_prediction --vertex --sync --run-date 2024-01-01
```

Flags:
- `--vertex` -- submit to Vertex AI Pipelines directly
- `--sync` -- block until the pipeline completes (or fails)
- `--run-date 2024-01-01` -- **required** for seed data alignment. The
  BigQueryExtract query uses a 90-day window: `WHERE event_date BETWEEN
  DATE_SUB('2024-01-01', INTERVAL 90 DAY) AND '2024-01-01'`, covering Oct 3 2023
  to Jan 1 2024. The seed data has dates from Oct-Dec 2023.

### 16b. Expected timeline

| Step | Duration | Notes |
|------|----------|-------|
| bigquery-extract | ~30-80s | Query raw_user_events, export Parquet to GCS |
| bq-transform | ~30-40s | Feature engineering SQL |
| write-features | ~40-50s | Register as Feature Store FeatureGroup |
| train-model | ~3-5 min | Vertex Custom Training Job (LogisticRegression) |
| evaluate-model | ~60s | Compute AUC/F1, check gate (AUC >= 0.78) |
| deploy-model | ~15-20 min | Upload to Model Registry, deploy to Endpoint |

Total: ~25-30 minutes (dominated by endpoint provisioning in deploy-model).

### 16c. Monitor the pipeline

The CLI prints a Vertex AI console URL. You can also check via gcloud:

```bash
gcloud ai pipeline-jobs list --region=us-east4 --project=prj-0n-dta-pt-ai-sandbox \
  --filter="displayName~churn" --format="table(name,state,createTime)"
```

### 16d. Re-runs and caching

The framework compiles with `enable_caching=False` by default (via
RunPipelineJobOperator), preventing stale cache hits after teardown or data
changes. To explicitly control caching on direct Vertex AI submission:

```bash
uv run gml run churn_prediction --vertex --sync --run-date 2024-01-01 --no-cache
```

---

## 17. Run churn_prediction via Composer

This is the production path: Composer DAG triggers the Vertex AI pipeline.

### 17a. Deploy and trigger

```bash
# Deploy the DAG (if not already done in Step 14)
uv run gml deploy churn_prediction

# Wait ~5 min for Composer to parse the DAG, then trigger
uv run gml run churn_prediction --composer --run-date 2024-01-01
```

The compiled DAG contains a single `RunPipelineJobOperator` that:
- Points to the compiled KFP YAML on GCS
- Passes `parameter_values={"run_date": "{{ ds }}"}` (Airflow templates the logical date)
- Runs the Vertex pipeline as the Pipeline SA (which has BQ/GCS/AR permissions)
- Uses `deferrable=True` to free the Airflow worker slot while the Vertex pipeline runs
- Disables caching (`enable_caching=False`) to prevent stale results

---

## 18. Run recommendation_engine on Composer + Vertex AI

`recommendation_engine` is the hybrid pattern: a Composer DAG orchestrates
two sequential Vertex AI pipelines plus BQ and email tasks.

### 18a. Deploy and trigger

```bash
# Deploy (compiles, verifies images, uploads DAG + 2 pipeline YAMLs)
uv run gml deploy recommendation_engine

# Wait ~5 min for Composer to parse the DAG, then trigger
uv run gml run recommendation_engine --composer --run-date 2026-03-01
```

### 18b. Flow on GCP

```
Composer DAG:
  extract_data (BigQueryInsertJobOperator)
    |
    v
  compute_features (RunPipelineJobOperator -> reco_features Vertex Pipeline)
    |  ingest -> transform -> transform
    v
  train_model (RunPipelineJobOperator -> reco_training Vertex Pipeline)
    |  ingest -> transform -> train
    v
  notify (EmailOperator -- fails in DEV, no SMTP)
```

### 18c. Docker images required

Both `component-base` and `recommendation-engine-trainer` must be in AR with
the correct `{branch}-{sha}` tag. If images were built but tagged with an old
SHA, `gml deploy` auto-retags them.

---

## 19. Verify Results

### 19a. BigQuery tables

```bash
BQ_DATASET=dsci_gcpdemo_test

# sales_analytics
bq query --project_id=prj-0n-dta-pt-ai-sandbox --use_legacy_sql=false \
  "SELECT * FROM \`${BQ_DATASET}.daily_report\` ORDER BY category"

# churn_prediction
bq query --project_id=prj-0n-dta-pt-ai-sandbox --use_legacy_sql=false \
  "SELECT table_id, row_count FROM \`${BQ_DATASET}.__TABLES__\`
   WHERE table_id IN ('churn_training_raw','churn_features_engineered')
   ORDER BY table_id"

# recommendation_engine
bq query --project_id=prj-0n-dta-pt-ai-sandbox --use_legacy_sql=false \
  "SELECT table_id, row_count FROM \`${BQ_DATASET}.__TABLES__\`
   WHERE table_id LIKE 'reco_%'
   ORDER BY table_id"
```

### 19b. Model in GCS

```bash
gsutil ls gs://prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo/test/models/churn_prediction/latest/
# Expected: model.pkl
```

### 19c. Vertex AI Endpoint (if deploy-model ran)

```bash
gcloud ai endpoints list --region=us-east4 --project=prj-0n-dta-pt-ai-sandbox
```

**Important**: Deployed endpoints incur per-hour charges. See [Teardown](#20-teardown)
for cleanup.

### 19d. Airflow UI

The Airflow UI URL is printed by `gml run --composer`. You can also find it:

```bash
gcloud composer environments describe mlopshousingpoc \
  --location us-east4 \
  --format='value(config.airflowUri)'
```

---

## 20. Teardown

### 20a. Clean up branch resources

`gml teardown` removes all ephemeral resources namespaced to a branch:

```bash
# Preview what will be deleted
uv run gml teardown --branch test --dry-run

# Delete (requires confirmation)
uv run gml teardown --branch test --confirm
```

This deletes:
- Composer DAG files from the GCS bucket
- Airflow DAG metadata (runs, task instances)
- GCS objects under `gs://{bucket}/{branch}/`
- BigQuery dataset `{namespace_bq}`

Safety: teardown only works on DEV branches. It refuses to delete STAGING (`main`)
or PROD (`v*`) resources.

### 20b. Undeploy Vertex AI endpoints (avoid charges)

Deployed endpoints incur per-hour charges for provisioned VMs:

```bash
# List endpoints
gcloud ai endpoints list --region=us-east4 --project=prj-0n-dta-pt-ai-sandbox

# Undeploy model from endpoint
gcloud ai endpoints undeploy-model ENDPOINT_ID \
  --deployed-model-id=DEPLOYED_MODEL_ID \
  --region=us-east4 \
  --project=prj-0n-dta-pt-ai-sandbox

# Or delete the endpoint entirely
gcloud ai endpoints delete ENDPOINT_ID \
  --region=us-east4 \
  --project=prj-0n-dta-pt-ai-sandbox
```

### 20c. Destroy Terraform infrastructure

Only do this when you're done with the entire environment:

```bash
cd terraform/envs/dev
terraform destroy
```

This removes the Artifact Registry and GCS bucket (in the enterprise scenario).
In the greenfield scenario, it also removes Composer, IAM, and WIF resources.
Composer destruction takes 10-15 minutes.

---

## Appendix A: CLI Reference

| Command | Description |
|---------|------------|
| `gml context show` | Display resolved namespace and resource names |
| `gml context show --json` | Machine-readable JSON output |
| `gml context show --branch X` | Inspect context for a different branch |
| `gml compile <name>` | Compile one pipeline to KFP YAML and/or Airflow DAG |
| `gml compile --all` | Compile all pipelines |
| `gml deploy <name>` | Compile + verify images + upload artifacts to GCS/Composer |
| `gml deploy --all` | Deploy everything |
| `gml deploy --all --dry-run` | Preview what would be deployed |
| `gml run <name> --local` | Execute locally with DuckDB stubs |
| `gml run <name> --local --dry-run` | Preview execution plan |
| `gml run <name> --vertex` | Submit to Vertex AI Pipelines |
| `gml run <name> --vertex --sync` | Submit and wait for completion |
| `gml run <name> --vertex --no-cache` | Submit with step caching disabled |
| `gml run <name> --composer` | Trigger deployed DAG on Cloud Composer |
| `gml run <name> --composer --run-date DATE` | Trigger with specific logical date |
| `gml teardown --branch <name>` | Clean up branch-namespaced DEV resources |
| `gml teardown --branch <name> --dry-run` | Preview what would be deleted |
| `gml init project <team> <project>` | Scaffold a new project |
| `gml init pipeline <name>` | Scaffold a new pipeline |

All run commands accept `--run-date YYYY-MM-DD` (defaults to today).

---

## Appendix B: Docker Image Hierarchy

```
python:3.11-slim                              (upstream, ~150 MB)
  +-- base-python:{branch}-{sha}              (+ build-essential, curl)
        |
        +-- component-base:{branch}-{sha}     (+ GCP SDKs, pyarrow, pandas, db-dtypes, kfp)
        |     Used by: bigquery-extract, bq-transform, write-features,
        |              evaluate-model, deploy-model (KFP components)
        |
        +-- base-ml:{branch}-{sha}            (+ numpy, sklearn, xgboost, lightgbm)
              +-- churn-prediction-trainer:{branch}-{sha}
              |     (+ pipeline-specific requirements.txt)
              |     Used by: train-model step in churn_prediction
              |
              +-- recommendation-engine-trainer:{branch}-{sha}
                    (+ pipeline-specific requirements.txt)
                    Used by: train-model step in recommendation_engine
```

Why two branches from base-python?

- **component-base**: GCP SDKs only. Most KFP steps just query BQ, read/write GCS,
  call Vertex APIs. Adding ML libraries would double image size for no benefit.
- **base-ml**: ML libraries without GCP component SDKs. Trainers use BQ/GCS
  clients from their own `requirements.txt`.
- **evaluate-model**: Uses component-base + pip-installs `scikit-learn` at runtime
  (~15s). This avoids a third base image for a single step.

---

## Appendix C: Resource Naming

All GCP resources are derived from `{team}-{project}-{branch}`:

| Resource | Pattern | Example (branch=test) |
|----------|---------|-----------------------|
| Namespace | `{team}-{project}-{branch}` | `dsci-gcpdemo-test` |
| BQ dataset | `{ns_bq}` (underscored, max 30 chars) | `dsci_gcpdemo_test` |
| GCS bucket | `{project_id}-{team}-{project}` | `prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo` |
| GCS prefix | `gs://{bucket}/{branch}/` | `gs://prj-0n-dta-pt-ai-sandbox-dsci-gcpdemo/test/` |
| AR repo | `{team}-{project}` | `dsci-gcpdemo` |
| Image tag | `{branch}-{sha}` | `test-a88424d` |
| DAG ID | `{ns_bq}__{pipeline}` | `dsci_gcpdemo_test__sales_analytics` |
| Vertex experiment | `{ns}-{pipeline}-exp` | `dsci-gcpdemo-test-churn-prediction-exp` |

Note: GCS bucket includes the GCP `project_id` as a prefix for global uniqueness.
AR repos are project-scoped and don't need the project_id prefix.

---

## Appendix D: Run-Date Alignment

Seed data has specific date ranges. Using the wrong `--run-date` produces empty
results (0 rows from BQ queries with date filters).

| Pipeline | Seed Date Range | Correct --run-date |
|----------|----------------|-------------------|
| churn_prediction | Oct 15 - Dec 23, 2023 | `2024-01-01` (90-day lookback covers seed dates) |
| sales_analytics | Around 2026-03-01 | `2026-03-01` |
| recommendation_engine | Around 2026-03-01 | `2026-03-01` |

If `--run-date` is omitted, the framework defaults to today's date. For
production use this is correct (data is current); for demo/testing with seed
data, always specify the date explicitly.

---

## Appendix E: Common Issues

### "No module named 'sklearn'" in evaluate-model

The component-base image excludes ML libraries by design. The evaluate_model
component pip-installs `scikit-learn` at runtime (~15s). This is expected.

### Empty training data (0 rows)

The BigQueryExtract query uses a date window relative to `run_date`. If the
window doesn't cover the seed data dates, 0 rows are returned. See
[Appendix D](#appendix-d-run-date-alignment) for correct dates.

### Terraform IAM race condition

First `terraform apply` may fail with a Composer IAM error (greenfield scenario
only). Re-run `terraform apply` -- it's idempotent.

### Composer cold-start latency

First DAG trigger on SMALL Composer 3 takes 15-20 minutes (GKE Autopilot worker
provisioning). Subsequent triggers are fast.

### Image tag mismatch after new commits

The compiler generates image tags as `{branch}-{short_sha}`. When you make new
commits, the SHA changes, so compiled artifacts reference tags that don't exist
in AR. `gml deploy` auto-retags matching images. If that fails, rebuild and push:

```bash
export IMAGE_TAG=$(git rev-parse --abbrev-ref HEAD | tr '[:upper:]/' '[:lower:]-')-$(git rev-parse --short HEAD)
./scripts/docker_build.sh --push
```

### "Gate failures: auc=0.5000 < 0.78" during local run

This happens when running `churn_prediction --local` **without `--run-date`**.
The default date is today, which returns 0 rows from the seed data, so
EvaluateModel falls back to placeholder metrics (0.50). Fix: use
`--run-date 2024-01-01` to match the seed data date range.

### Composer DAG not appearing after deploy

Composer 3 needs ~5 minutes to parse new DAG files. Wait, then check the
Airflow UI. If the DAG still doesn't appear, check the Airflow scheduler logs
for Python syntax errors in the generated DAG file.

### notify task fails on Composer

Expected in DEV -- no SMTP server configured. The EmailOperator task requires
an `smtp_default` Airflow connection. All upstream tasks should complete
successfully. In STAGING/PROD, SMTP would be configured.

### Composer 3 worker crash (`check_python_version`)

Composer 3 workers intermittently crash during import of
`RunPipelineJobOperator` or `BigQueryInsertJobOperator` due to a bug in
`google.api_core._python_version_support.check_python_version()`. This is a
GCP infrastructure issue, not a code bug. Symptoms:

- Tasks show as "queued" with start/end dates but never transition to "success"
- Zombie job detection messages in Airflow logs
- Downstream tasks stuck in "None" state

**Workaround**: Wait 5-15 minutes for the worker pod to restart, then
re-trigger. The issue self-heals.

### DEV DAGs have schedule=None

By design, DEV-environment DAGs are compiled with `schedule=None` (manual trigger
only). This prevents auto-scheduled runs from consuming stale seed data.
STAGING and PROD DAGs retain the declared schedule.

### Terraform state bucket hardcoded

The GCS backend bucket in `terraform/envs/dev/main.tf` may reference an old
project's state bucket. Update the `backend "gcs"` block to point to your own
state bucket, or switch to a local backend for demos.
