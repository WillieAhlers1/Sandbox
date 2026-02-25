# GCP Infrastructure Setup Guide

> **Audience:** Platform / Infrastructure teams provisioning GCP resources for the ML Framework.
> **Scope:** One-time setup per GCP project. Run for each environment (DEV, STAGING, PROD).
> **Automation:** A `bootstrap.sh` script automates most of this via `gcloud`. This document covers both the console (UI) and CLI paths.

---

## Table of Contents

1. [Environment Architecture](#1-environment-architecture)
2. [Prerequisites](#2-prerequisites)
3. [GCP Projects](#3-gcp-projects)
4. [Enable Required APIs](#4-enable-required-apis)
5. [Cloud Storage (GCS)](#5-cloud-storage-gcs)
6. [BigQuery](#6-bigquery)
7. [Artifact Registry](#7-artifact-registry)
8. [Secret Manager](#8-secret-manager)
9. [Vertex AI](#9-vertex-ai)
10. [Vertex AI Feature Store](#10-vertex-ai-feature-store)
11. [Cloud Composer (Airflow)](#11-cloud-composer-airflow)
12. [IAM — Service Account & Roles](#12-iam--service-account--roles)
13. [Workload Identity Federation (GitHub Actions)](#13-workload-identity-federation-github-actions)
14. [GitHub Repository Configuration](#14-github-repository-configuration)
15. [Adding Team Members](#15-adding-team-members)
16. [Resource Naming Convention](#16-resource-naming-convention)
17. [Cost Estimates & Optimization](#17-cost-estimates--optimization)
18. [Provisioning Checklist](#18-provisioning-checklist)

---

## 1. Environment Architecture

The framework uses **three isolated GCP projects** mapped to git state. The git branch determines which project is targeted — there is no manual environment selection in application code.

| Git State | Environment | GCP Project | Lifecycle |
|---|---|---|---|
| `feature/*`, `hotfix/*`, any branch | **DEV** | `gcp-gap-demo-dev` | Ephemeral — auto-cleaned on PR merge |
| `main` | **STAGING** | `gcp-gap-demo-staging` | Persistent — full pipeline runs |
| Release tag (`v*`) | **PROD** | `gcp-gap-demo-prod` | Immutable — promoted from STAGING only |
| `prod/*` branches | **PROD-EXP** | `gcp-gap-demo-prod` | Isolated A/B experiments in PROD |

PROD is **never deployed to directly from source code**. Only validated STAGING artifacts are promoted via release tags.

### Region

All resources must be provisioned in **`us-central1`**. Multi-region support is deferred.

---

## 2. Prerequisites

Before provisioning any resources, ensure:

- A **Google Cloud billing account** is created and linked to all three projects
- The provisioning user has the **Owner** (`roles/owner`) role on each project
- For CLI automation: `gcloud` CLI is installed and authenticated (`gcloud auth login`)

---

## 3. GCP Projects

Three projects are required. If not already created:

| Project Display Name | Project ID | Purpose |
|---|---|---|
| GCP GAP Demo Dev | `gcp-gap-demo-dev` | Feature branches, local-to-cloud development |
| GCP GAP Demo Staging | `gcp-gap-demo-staging` | Main branch, full integration testing |
| GCP GAP Demo Prod | `gcp-gap-demo-prod` | Production workloads, model serving |

### Console

1. Navigate to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown (top bar) → **New Project**
3. Set the **Project name** and **Project ID** as listed above
4. Click **Create**
5. After creation, go to **Billing** and link a billing account to the project

### CLI

```bash
gcloud projects create gcp-gap-demo-dev --name="GCP GAP Demo Dev"
gcloud projects create gcp-gap-demo-staging --name="GCP GAP Demo Staging"
gcloud projects create gcp-gap-demo-prod --name="GCP GAP Demo Prod"

# Link billing (replace BILLING_ACCOUNT_ID with your billing account)
gcloud billing projects link gcp-gap-demo-dev --billing-account=BILLING_ACCOUNT_ID
gcloud billing projects link gcp-gap-demo-staging --billing-account=BILLING_ACCOUNT_ID
gcloud billing projects link gcp-gap-demo-prod --billing-account=BILLING_ACCOUNT_ID
```

---

## 4. Enable Required APIs

The following APIs must be enabled in **every** project (dev, staging, prod).

| API | Service Name | Purpose |
|---|---|---|
| Vertex AI API | `aiplatform.googleapis.com` | ML pipelines, experiments, model registry, endpoints, feature store |
| BigQuery API | `bigquery.googleapis.com` | Data warehousing, SQL transforms, feature tables |
| Cloud Storage API | `storage.googleapis.com` | Object storage for pipeline artifacts, model files, DAGs |
| Secret Manager API | `secretmanager.googleapis.com` | Runtime secret resolution (`!secret` references) |
| Cloud Composer API | `composer.googleapis.com` | Managed Apache Airflow for DAG scheduling |
| Artifact Registry API | `artifactregistry.googleapis.com` | Docker image storage for training containers |
| IAM API | `iam.googleapis.com` | Service account and role management |
| Cloud Resource Manager API | `cloudresourcemanager.googleapis.com` | Project-level resource operations |
| Compute Engine API | `compute.googleapis.com` | Required by Vertex AI (training VMs) and Composer (worker nodes) |
| Cloud Build API | `cloudbuild.googleapis.com` | Docker image builds for Artifact Registry |

### Console

For each project:

1. Switch to the target project (project dropdown, top bar)
2. Navigate to **APIs & Services → Library**
3. Search for each API by name and click **Enable**
4. Repeat for all APIs listed above

Note: BigQuery API, Cloud Storage API, IAM API, and Cloud Resource Manager API are often pre-enabled on new projects. Verify by checking **APIs & Services → Enabled APIs & services**.

### CLI

```bash
# Run for each project
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  echo "==> Enabling APIs for ${PROJECT}..."
  gcloud services enable \
    aiplatform.googleapis.com \
    bigquery.googleapis.com \
    storage.googleapis.com \
    secretmanager.googleapis.com \
    composer.googleapis.com \
    artifactregistry.googleapis.com \
    iam.googleapis.com \
    cloudresourcemanager.googleapis.com \
    compute.googleapis.com \
    cloudbuild.googleapis.com \
    --project="${PROJECT}"
done
```

---

## 5. Cloud Storage (GCS)

The framework uses one GCS bucket per team+project. Branches share the bucket via path prefixes (`gs://{team}-{project}/{branch}/`).

| Setting | Value |
|---|---|
| **Bucket name** | `dsci-example-churn` (pattern: `{team}-{project}`) |
| **Location type** | Region |
| **Region** | `us-central1` |
| **Storage class** | Standard |
| **Access control** | Uniform |
| **Public access** | Enforce prevention (default) |
| **Versioning** | Disabled (default) |
| **Retention** | None |

> **Note:** GCS bucket names are globally unique. If the name is taken, prefix with the org or project ID (e.g., `gcp-gap-demo-dsci-example-churn`). Update `framework.yaml` accordingly.

### Console

1. Navigate to **Cloud Storage → Buckets**
2. Click **Create**
3. Enter the bucket name, select Region / `us-central1` / Standard
4. Leave access control as Uniform, public access prevention enforced
5. Click **Create**

### CLI

```bash
# One bucket per environment (adjust naming if needed for global uniqueness)
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  gsutil mb -p "${PROJECT}" -l us-central1 -c standard "gs://dsci-example-churn-${PROJECT##*-}/"
done
```

### What goes in this bucket

| Path Pattern | Contents |
|---|---|
| `{branch}/pipelines/{name}/` | Vertex AI pipeline root (artifacts, metadata) |
| `{branch}/data/raw/` | Ingested raw data |
| `{branch}/data/processed/` | Transformed data |
| `{branch}/models/{name}/{version}/` | Trained model artifacts |
| `dags/` | Composer DAG files (Composer bucket, separate from above) |

---

## 6. BigQuery

BigQuery datasets are created **dynamically** by the framework using the naming convention `{team}_{project}_{branch_safe}` (e.g., `dsci_example_churn_feature_user_embeddings`). No manual dataset creation is required for branch-specific datasets.

However, you may want to create a **seed dataset** for shared source data:

| Setting | Value |
|---|---|
| **Dataset ID** | `dsci_example_churn_raw` or as needed |
| **Data location** | `us-central1` |
| **Default table expiration** | None (or set a TTL for DEV) |
| **Encryption** | Google-managed key |

### Console

1. Navigate to **BigQuery** (from the navigation menu)
2. In the Explorer panel, click the **⋮** menu next to your project name
3. Click **Create dataset**
4. Enter the Dataset ID, select `us-central1`, leave other defaults
5. Click **Create Dataset**

### CLI

```bash
bq mk --location=us-central1 --project_id=gcp-gap-demo-dev dsci_example_churn_raw
```

---

## 7. Artifact Registry

One Docker repository per team+project. Shared across branches; images are tagged with `{branch_safe}-{git_sha}` for traceability.

| Setting | Value |
|---|---|
| **Repository name** | `dsci-example-churn` (pattern: `{team}-{project}`) |
| **Format** | Docker |
| **Mode** | Standard |
| **Location type** | Region |
| **Region** | `us-central1` |
| **Encryption** | Google-managed key |
| **Immutable tags** | Disabled |

Full registry path: `us-central1-docker.pkg.dev/{project_id}/dsci-example-churn`

### Console

1. Navigate to **Artifact Registry**
2. Click **Create Repository**
3. Enter name `dsci-example-churn`, select Docker, Region, `us-central1`
4. Click **Create**

### CLI

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  gcloud artifacts repositories create dsci-example-churn \
    --repository-format=docker \
    --location=us-central1 \
    --description="ML Framework container images" \
    --project="${PROJECT}"
done
```

---

## 8. Secret Manager

Secrets are referenced in pipeline code as `!secret <key-name>` and resolved at runtime. The framework prepends the branch namespace: `{team}-{project}-{branch}-{key-name}`.

Example: a database password on the `main` branch → Secret name: `dsci-example-churn-main-db-password`

### Console

1. Navigate to **Security → Secret Manager**
2. Click **Create Secret**
3. Enter the secret **Name** following the `{namespace}-{key}` pattern
4. Enter the **Secret value**
5. Select **Automatic** replication
6. Click **Create Secret**

### CLI

```bash
echo -n "my-secret-value" | gcloud secrets create dsci-example-churn-main-db-password \
  --replication-policy="automatic" \
  --data-file=- \
  --project=gcp-gap-demo-staging
```

### Naming Convention

| Branch Context | Secret Name Pattern | Example |
|---|---|---|
| `main` | `{team}-{project}-main-{key}` | `dsci-example-churn-main-db-password` |
| `feature/user-embeddings` | `{team}-{project}-feature--user-embeddings-{key}` | `dsci-example-churn-feature--user-embeddings-api-key` |
| PROD (stable alias) | `{team}-{project}-prod-{key}` | `dsci-example-churn-prod-db-password` |

> **Tip:** For DEV, you can set secrets via environment variables locally instead of creating them in Secret Manager: `export GML_SECRET_DB_URL="postgres://localhost/mydb"`

---

## 9. Vertex AI

Vertex AI resources (pipelines, experiments, endpoints, model registry entries) are created **programmatically** by the framework at runtime. No manual provisioning is required beyond ensuring the API is enabled (Section 4).

### Verify Vertex AI is accessible

1. Navigate to **Vertex AI → Dashboard**
2. If prompted, click **Enable All Recommended APIs** (this activates sub-services like Notebooks, Training, etc.)
3. Confirm the Dashboard loads without errors

### Resources created by the framework

| Resource Type | Created By | Naming Pattern |
|---|---|---|
| Pipeline Runs | `gml run --vertex` | `{namespace}-{pipeline_name}-{timestamp}` |
| Experiments | `gml run --vertex` | `{namespace}-{pipeline_name}-exp` |
| Models | `TrainModel` component | `{namespace}-{model_name}` |
| Endpoints | `DeployModel` component | `{namespace}-{model_name}-endpoint` |
| Training Jobs | `TrainModel` component | `{namespace}-{job_name}` |

---

## 10. Vertex AI Feature Store

The framework uses **Vertex AI Feature Store with Bigtable-backed online serving** for low-latency feature reads during model inference. Offline/batch reads go directly to BigQuery source tables.

> **Cost warning:** Bigtable-backed online serving incurs ongoing cost (~$0.65/node/hour ≈ ~$470/month for 1 node). Provision only when online feature serving is needed. DEV environments can defer this.

| Setting | DEV | STAGING | PROD |
|---|---|---|---|
| **Feature Store name** | `dsci-example-churn` | `dsci-example-churn` | `dsci-example-churn` |
| **Region** | `us-central1` | `us-central1` | `us-central1` |
| **Online serving type** | Bigtable | Bigtable | Bigtable |
| **Fixed node count** | 1 | Scale as needed | Scale as needed |
| **Min node count** | 1 | 1 | 3 (recommended) |

### Console

1. Navigate to **Vertex AI → Feature Store**
2. Click **Create Feature Online Store**
3. Enter name `dsci-example-churn` (pattern: `{team}-{project}`)
4. Select region `us-central1`
5. Select **Bigtable** for online serving
6. Set node counts per environment table above
7. Click **Create**

Entity types and feature views are managed programmatically via `gml deploy features`. The framework reads `feature_schemas/*.yaml` and calls the Feature Store API to create/update entities and views.

### Feature views are branch-namespaced

Each branch writes to its own feature view (e.g., `user_churn_signals_feature_user_embeddings`), ensuring DEV experiments never contaminate PROD online serving.

---

## 11. Cloud Composer (Airflow)

Cloud Composer is the managed Airflow service that executes pipeline DAGs on a schedule.

> **Cost warning:** Cloud Composer is the most expensive resource in this stack. A small Composer 2 environment costs ~$300–$500/month. Provision only when scheduled pipeline orchestration is required. For early development, use `gml run --local` or `gml run --vertex` directly.

| Setting | DEV | STAGING | PROD |
|---|---|---|---|
| **Environment name** | `ml-composer-env` | `ml-composer-env` | `ml-composer-env` |
| **Composer version** | Composer 2 (latest) | Composer 2 (latest) | Composer 2 (latest) |
| **Region** | `us-central1` | `us-central1` | `us-central1` |
| **Environment size** | Small | Medium | Medium/Large |
| **Image version** | Latest `composer-2.x.x-airflow-2.x.x` | Same | Same |

### Console

1. Navigate to **Composer**
2. Click **Create Environment** → Select **Composer 2**
3. Enter name `ml-composer-env`
4. Select location `us-central1`
5. Select environment size per table above
6. Under **Environment variables**, add:
   - `GML_TEAM` = `dsci`
   - `GML_PROJECT` = `example-churn`
   - `GML_GCP__REGION` = `us-central1`
   - `GML_GCP__DEV_PROJECT_ID` = `gcp-gap-demo-dev` (for DEV env; use the correct project ID per environment)
7. Leave networking and advanced settings as defaults unless org policies require otherwise
8. Click **Create**

> Provisioning takes **20–30 minutes**.

### After creation

1. Click on the environment name in the Composer list
2. Note the **DAGs folder** GCS path from the Environment Configuration tab (e.g., `gs://us-central1-ml-composer-env-XXXXX-bucket/dags/`)
3. The `gml deploy dags` command syncs generated DAG files to this bucket

---

## 12. IAM — Service Account & Roles

A dedicated service account is used by the framework for all GCP operations. Create one in **each** project.

| Setting | Value |
|---|---|
| **Service account name** | `gcp-ml-framework-sa` |
| **Service account ID** | `gcp-ml-framework-sa` |
| **Email** | `gcp-ml-framework-sa@{PROJECT_ID}.iam.gserviceaccount.com` |

### Required IAM Roles

| Role | Role ID | Purpose |
|---|---|---|
| BigQuery Data Editor | `roles/bigquery.dataEditor` | Create/read/write BQ datasets and tables |
| BigQuery Job User | `roles/bigquery.jobUser` | Execute BigQuery queries |
| Storage Object Admin | `roles/storage.objectAdmin` | Full access to GCS bucket objects |
| Vertex AI User | `roles/aiplatform.user` | Create/run pipelines, experiments, deploy models |
| Secret Manager Secret Accessor | `roles/secretmanager.secretAccessor` | Read secret values at runtime |
| Composer Worker | `roles/composer.worker` | Interact with Cloud Composer |

### Console

1. Navigate to **IAM & Admin → Service Accounts**
2. Click **Create Service Account**
3. Enter name `gcp-ml-framework-sa` and description `ML Framework pipeline service account`
4. Click **Create and Continue**
5. On the "Grant this service account access to project" step, add **all six roles** from the table above (click "Add Another Role" for each)
6. Click **Continue** → **Done**
7. Repeat in each of the three projects

### CLI

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  SA_NAME="gcp-ml-framework-sa"
  SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

  # Create service account
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="ML Framework pipeline service account" \
    --project="${PROJECT}"

  # Grant roles
  for ROLE in \
    roles/bigquery.dataEditor \
    roles/bigquery.jobUser \
    roles/storage.objectAdmin \
    roles/aiplatform.user \
    roles/secretmanager.secretAccessor \
    roles/composer.worker; do
    gcloud projects add-iam-policy-binding "${PROJECT}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="${ROLE}" \
      --quiet
  done
done
```

---

## 13. Workload Identity Federation (GitHub Actions)

Workload Identity Federation enables GitHub Actions to authenticate to GCP **without storing long-lived JSON key files**. This is the recommended approach for CI/CD.

### Architecture

```
GitHub Actions (OIDC token) → Workload Identity Pool → Service Account → GCP Resources
```

### Setup per project

#### 13a. Create Workload Identity Pool

**Console:**

1. Navigate to **IAM & Admin → Workload Identity Federation**
2. Click **Create Pool**
3. Name: `GitHub Actions Pool`, Pool ID: `github-pool`
4. Click **Continue**

**CLI:**

```bash
gcloud iam workload-identity-pools create github-pool \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  --project="${PROJECT}"
```

#### 13b. Add OIDC Provider

**Console:**

1. In the pool just created, click **Add Provider**
2. Select **OpenID Connect (OIDC)**
3. Provider name: `GitHub OIDC Provider`, Provider ID: `github-provider`
4. Issuer URL: `https://token.actions.githubusercontent.com`
5. Audiences: Default audience
6. Attribute mapping:
   - `google.subject` = `assertion.sub`
   - `attribute.repository` = `assertion.repository`
7. Click **Save**

**CLI:**

```bash
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="${PROJECT}"
```

#### 13c. Bind Service Account to GitHub Repository

This step authorizes a specific GitHub repository to impersonate the service account.

Replace `YOUR_GITHUB_ORG` and `YOUR_REPO_NAME` with your actual values.

**Console:**

1. Navigate to **IAM & Admin → Service Accounts**
2. Click on `gcp-ml-framework-sa`
3. Go to the **Permissions** tab
4. Click **Grant Access**
5. New principal (enter the full principal set string):
   ```
   principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO_NAME
   ```
6. Role: **Workload Identity User** (`roles/iam.workloadIdentityUser`)
7. Click **Save**

> **Finding your Project Number:** Go to the project **Dashboard** (Navigation menu → Cloud overview → Dashboard). The **Project number** is displayed on the Project info card. It is a numeric ID, different from the Project ID.

**CLI:**

```bash
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
SA_EMAIL="gcp-ml-framework-sa@${PROJECT}.iam.gserviceaccount.com"
PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${PROVIDER_RESOURCE}/attribute.repository/YOUR_GITHUB_ORG/YOUR_REPO_NAME" \
  --project="${PROJECT}"
```

#### 13d. Record Output Values

After setup, record these values for GitHub configuration (Section 14):

| Value | How to Obtain |
|---|---|
| WIF Provider resource name | `projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| Service account email | `gcp-ml-framework-sa@{PROJECT_ID}.iam.gserviceaccount.com` |
| Project ID | `gcp-gap-demo-dev` / `gcp-gap-demo-staging` / `gcp-gap-demo-prod` |

---

## 14. GitHub Repository Configuration

After provisioning GCP resources, configure the GitHub repository with the values from Section 13.

### Repository Secrets (Settings → Secrets and variables → Actions → Secrets)

| Secret Name | Value | Source |
|---|---|---|
| `WIF_PROVIDER_DEV` | `projects/{DEV_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider` | Section 13d |
| `WIF_PROVIDER_STAGING` | `projects/{STAGING_NUMBER}/locations/global/...` | Section 13d |
| `WIF_PROVIDER_PROD` | `projects/{PROD_NUMBER}/locations/global/...` | Section 13d |
| `SA_EMAIL_DEV` | `gcp-ml-framework-sa@gcp-gap-demo-dev.iam.gserviceaccount.com` | Section 12 |
| `SA_EMAIL_STAGING` | `gcp-ml-framework-sa@gcp-gap-demo-staging.iam.gserviceaccount.com` | Section 12 |
| `SA_EMAIL_PROD` | `gcp-ml-framework-sa@gcp-gap-demo-prod.iam.gserviceaccount.com` | Section 12 |

### Repository Variables (Settings → Secrets and variables → Actions → Variables)

| Variable Name | Value |
|---|---|
| `GCP_PROJECT_ID_DEV` | `gcp-gap-demo-dev` |
| `GCP_PROJECT_ID_STAGING` | `gcp-gap-demo-staging` |
| `GCP_PROJECT_ID_PROD` | `gcp-gap-demo-prod` |
| `GML_TEAM` | `dsci` |
| `GML_PROJECT` | `example-churn` |

---

## 15. Adding Team Members

### Grant project access (Console)

1. Navigate to **IAM & Admin → IAM**
2. Click **Grant Access**
3. Enter the team member's **Google email address**
4. Assign one or more roles:

| Team Role | Recommended GCP Roles |
|---|---|
| **Data Scientist** (read/write data, run pipelines) | `roles/bigquery.dataEditor`, `roles/bigquery.jobUser`, `roles/aiplatform.user`, `roles/storage.objectAdmin` |
| **ML Engineer** (full pipeline + deployment access) | `roles/editor` (or the Data Scientist set + `roles/composer.user`) |
| **Platform / Infra** (full admin) | `roles/owner` |
| **Viewer** (read-only access to all resources) | `roles/viewer` |

5. Click **Save**
6. Repeat in each project the team member needs access to

### CLI

```bash
gcloud projects add-iam-policy-binding gcp-gap-demo-dev \
  --member="user:colleague@example.com" \
  --role="roles/editor"
```

---

## 16. Resource Naming Convention

All GCP resource names are derived from a canonical namespace token. The framework enforces this automatically — no hardcoded names in application code.

### Namespace Token

```
{team}-{project}-{branch}
```

Example: `dsci-example-churn-feature--user-embeddings`

### Resource Name Mapping

| GCP Resource | Pattern | Example |
|---|---|---|
| GCS path prefix | `gs://{team}-{project}/{branch}/` | `gs://dsci-example-churn/feature--user-embeddings/` |
| BigQuery dataset | `{team}_{project}_{branch_safe}` | `dsci_example_churn_feature__user_embeddings` |
| BigQuery table | `{dataset}.{entity}_{feature_group}` | `dsci_example_churn_main.feat_user_churn_signals` |
| Vertex AI Experiment | `{namespace}-{pipeline}-exp` | `dsci-example-churn-main-churn-prediction-exp` |
| Vertex AI Pipeline run | `{namespace}-{pipeline}-{timestamp}` | `dsci-example-churn-main-churn-prediction-20250225T060000` |
| Vertex AI Endpoint | `{namespace}-{model}-endpoint` | `dsci-example-churn-main-churn-v1-endpoint` |
| Composer DAG ID | `{namespace_bq}__{pipeline}` | `dsci_example_churn_main__churn_prediction` |
| Feature Store ID | `{team}-{project}` | `dsci-example-churn` |
| Feature View | `{entity}_{feature_group}_{branch_safe}` | `user_churn_signals_feature__user_embeddings` |
| Artifact Registry repo | `{team}-{project}` | `dsci-example-churn` |
| Docker image tag | `{branch_safe}-{git_sha}` | `feature--user-embeddings-a1b2c3d` |
| Secret name | `{namespace}-{key}` | `dsci-example-churn-main-db-password` |

---

## 17. Cost Estimates & Optimization

Approximate monthly costs per environment (us-central1 pricing, subject to change):

| Resource | DEV (Small) | STAGING (Medium) | PROD (Production) |
|---|---|---|---|
| Cloud Composer 2 | ~$300–500 | ~$400–600 | ~$500–1,000 |
| Vertex AI Feature Store (Bigtable) | ~$470/node | ~$470/node | ~$1,400 (3 nodes) |
| BigQuery | Pay-per-query (minimal) | Pay-per-query | Pay-per-query |
| Cloud Storage | < $10 | < $10 | < $50 |
| Artifact Registry | < $5 | < $5 | < $5 |
| Secret Manager | < $1 | < $1 | < $1 |
| Vertex AI Pipelines/Training | Pay-per-use | Pay-per-use | Pay-per-use |

### Cost optimization recommendations

- **DEV:** Defer Composer and Feature Store creation. Use `gml run --local` for development and `gml run --vertex` for ad-hoc cloud runs. Provision Composer only when scheduled DAG execution is needed.
- **STAGING:** Provision Composer and Feature Store only when full integration testing begins.
- **PROD:** Provision all resources. Consider autoscaling for Composer (environment size: Medium or Large) and higher Bigtable node counts (3+) for Feature Store based on traffic.
- **Ephemeral DEV cleanup:** The framework's `gml teardown` command and `teardown.yaml` CI workflow delete branch-specific resources (BQ datasets, GCS prefixes, Vertex experiments) on PR merge to control DEV cost accumulation.

---

## 18. Provisioning Checklist

Use this checklist for each environment. Items marked with ⏳ can be deferred until needed.

### Per-Project Checklist

| # | Resource | DEV | STAGING | PROD | Notes |
|---|---|---|---|---|---|
| 1 | GCP Project created | ☐ | ☐ | ☐ | |
| 2 | Billing linked | ☐ | ☐ | ☐ | Required before any API can be enabled |
| 3 | APIs enabled (10 APIs) | ☐ | ☐ | ☐ | Section 4 |
| 4 | GCS Bucket | ☐ | ☐ | ☐ | Section 5 |
| 5 | BigQuery seed dataset | ☐ | ☐ | ☐ | Optional — framework creates branch datasets |
| 6 | Artifact Registry repo | ☐ | ☐ | ☐ | Section 7 |
| 7 | Service Account + IAM roles | ☐ | ☐ | ☐ | Section 12 |
| 8 | Workload Identity Federation | ☐ | ☐ | ☐ | Section 13 |
| 9 | ⏳ Cloud Composer environment | ☐ | ☐ | ☐ | Section 11 — defer until scheduling needed |
| 10 | ⏳ Vertex AI Feature Store | ☐ | ☐ | ☐ | Section 10 — defer until online serving needed |
| 11 | Secret Manager secrets | ☐ | ☐ | ☐ | Create as needed per pipeline requirements |

### One-Time Checklist

| # | Task | Done | Notes |
|---|---|---|---|
| 12 | GitHub repo secrets configured | ☐ | Section 14 — WIF providers + SA emails |
| 13 | GitHub repo variables configured | ☐ | Section 14 — Project IDs + team/project identity |
| 14 | Team members granted access | ☐ | Section 15 |
| 15 | `framework.yaml` updated with actual project IDs | ☐ | Replace placeholder IDs |

---

## Appendix: Automated Bootstrap

The repository includes `scripts/bootstrap.sh` which automates Sections 4, 7, 12, and 13 via `gcloud` CLI:

```bash
# DEV
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project gcp-gap-demo-dev --env dev

# STAGING
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project gcp-gap-demo-staging --env staging

# PROD
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project gcp-gap-demo-prod --env prod
```

This script enables APIs, creates the service account with required roles, configures Workload Identity Federation, and creates the Artifact Registry repository. GCS buckets, Composer environments, and Feature Store instances must be created separately.
