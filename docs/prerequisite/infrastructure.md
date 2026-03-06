# Infrastructure Setup

> Two approaches: **Terraform** (recommended) or **manual gcloud CLI**.

## Prerequisites

- Google Cloud billing account linked to all projects
- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Owner role on each project (or sufficient IAM permissions)
- Terraform >= 1.5 (for the Terraform approach)

---

## Approach 1: Terraform (Recommended)

The project ships with Terraform modules in `terraform/` that provision all shared infrastructure.

### What Terraform Manages

| Module | Resource | Purpose |
|---|---|---|
| `modules/composer` | `google_composer_environment` | Cloud Composer 3 with workloads_config |
| `modules/artifact_registry` | `google_artifact_registry_repository` | Docker repos for ML containers |
| `modules/iam` | Service accounts + WIF | Composer SA, Pipeline SA, GitHub Actions OIDC |
| `modules/storage` | `google_storage_bucket` | GCS buckets with versioning |

### Per-Environment Configs

| Environment | Size | Workers | Config |
|---|---|---|---|
| dev | ENVIRONMENT_SIZE_SMALL | 1-3 | `terraform/envs/dev/terraform.tfvars` |
| staging | ENVIRONMENT_SIZE_SMALL | 1-4 | `terraform/envs/staging/terraform.tfvars` |
| prod | ENVIRONMENT_SIZE_MEDIUM | 2-6 | `terraform/envs/prod/terraform.tfvars` |

### Steps

1. **Edit tfvars** for your environment:

```bash
# terraform/envs/dev/terraform.tfvars
project_id   = "your-gcp-dev-project"
region       = "us-central1"
team         = "dsci"
project_name = "examplechurn"
environment  = "dev"
github_repo  = "your-org/your-repo"  # for WIF (leave empty to skip)
```

2. **Enable APIs** (required before Terraform can create resources):

```bash
for PROJECT in your-gcp-dev your-gcp-staging your-gcp-prod; do
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
    --project="${PROJECT}"
done
```

3. **Create the Terraform state bucket** (one-time):

```bash
gsutil mb -p your-gcp-dev -l us-central1 gs://your-project-terraform-state/
gsutil versioning set on gs://your-project-terraform-state/
```

Update the `backend "gcs"` block in each `terraform/envs/*/main.tf` to point to your state bucket.

4. **Init and apply**:

```bash
cd terraform/envs/dev
terraform init
terraform plan -var-file=terraform.tfvars   # review the plan
terraform apply -var-file=terraform.tfvars  # provision resources
```

Repeat for `staging` and `prod`.

5. **Update framework.yaml** with outputs:

```bash
terraform output composer_dags_path
# Copy the GCS path into framework.yaml -> gcp.composer_dags_path.dev
```

### What Terraform Creates

For each environment:
- **Composer SA** (`{team}-{project}-{env}-composer`) with `roles/composer.worker`, `roles/bigquery.dataEditor`, `roles/bigquery.user`, `roles/storage.objectAdmin`
- **Pipeline SA** (`{team}-{project}-{env}-pipeline`) with `roles/aiplatform.user`, `roles/bigquery.dataEditor`, `roles/bigquery.user`, `roles/storage.objectAdmin`, `roles/artifactregistry.reader`
- Composer SA can impersonate Pipeline SA (`roles/iam.serviceAccountUser`)
- **GCS bucket** (`{project_id}-{team}-{project}-{env}`) with versioning
- **Artifact Registry** Docker repo (`{team}-{project}-{env}`)
- **Cloud Composer 3** environment with workloads_config
- **(Optional)** Workload Identity Federation pool + provider for GitHub Actions

---

## Approach 2: Manual gcloud CLI

For environments where Terraform is not available.

### 1. Create GCP Projects

```bash
gcloud projects create your-gcp-dev --name="Dev Project"
gcloud projects create your-gcp-staging --name="Staging Project"
gcloud projects create your-gcp-prod --name="Prod Project"

# Link billing
gcloud billing projects link your-gcp-dev --billing-account=BILLING_ACCOUNT_ID
```

### 2. Enable APIs

```bash
for PROJECT in your-gcp-dev your-gcp-staging your-gcp-prod; do
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
    --project="${PROJECT}"
done
```

### 3. Create GCS Bucket

One bucket per team+project. Branches share the bucket via path prefixes.

```bash
for PROJECT in your-gcp-dev your-gcp-staging your-gcp-prod; do
  gsutil mb -p "${PROJECT}" -l us-central1 -c standard \
    "gs://dsci-examplechurn-${PROJECT##*-}/"
  gsutil versioning set on "gs://dsci-examplechurn-${PROJECT##*-}/"
done
```

### 4. Create Artifact Registry

```bash
for PROJECT in your-gcp-dev your-gcp-staging your-gcp-prod; do
  gcloud artifacts repositories create dsci-examplechurn \
    --repository-format=docker \
    --location=us-central1 \
    --project="${PROJECT}"
done
```

### 5. Create Service Accounts + IAM Roles

```bash
for PROJECT in your-gcp-dev your-gcp-staging your-gcp-prod; do
  SA_NAME="dsci-examplechurn-pipeline"
  SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="Pipeline SA" \
    --project="${PROJECT}"

  for ROLE in \
    roles/bigquery.dataEditor \
    roles/bigquery.user \
    roles/storage.objectAdmin \
    roles/aiplatform.user \
    roles/secretmanager.secretAccessor \
    roles/artifactregistry.reader; do
    gcloud projects add-iam-policy-binding "${PROJECT}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="${ROLE}" \
      --quiet
  done
done
```

### 6. Configure Workload Identity Federation (GitHub Actions)

```bash
PROJECT=your-gcp-dev  # repeat for each project

gcloud iam workload-identity-pools create github-actions-pool \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  --project="${PROJECT}"

gcloud iam workload-identity-pools providers create-oidc github-actions-provider \
  --location="global" \
  --workload-identity-pool="github-actions-pool" \
  --display-name="GitHub OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-condition="assertion.repository == 'your-org/your-repo'" \
  --project="${PROJECT}"

PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
SA_EMAIL="dsci-examplechurn-pipeline@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/your-org/your-repo" \
  --project="${PROJECT}"
```

### 7. Set GitHub Repository Secrets

| Secret | Value |
|---|---|
| `WIF_PROVIDER_DEV` | `projects/{NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider` |
| `WIF_PROVIDER_STAGING` | Same pattern for staging project |
| `WIF_PROVIDER_PROD` | Same pattern for prod project |
| `SA_EMAIL_DEV` | `dsci-examplechurn-pipeline@your-gcp-dev.iam.gserviceaccount.com` |
| `SA_EMAIL_STAGING` | Same pattern for staging |
| `SA_EMAIL_PROD` | Same pattern for prod |

GitHub repo variables:

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID_DEV` | `your-gcp-dev` |
| `GCP_PROJECT_ID_STAGING` | `your-gcp-staging` |
| `GCP_PROJECT_ID_PROD` | `your-gcp-prod` |

### 8. Cloud Composer 3 (Provision When Ready)

Composer costs ~$300-500/month. The Terraform module handles this automatically. For manual setup:

```bash
# Use GCP Console: Composer -> Create Environment -> Composer 3
# Name: dsci-examplechurn-dev
# Region: us-central1
# Environment size: ENVIRONMENT_SIZE_SMALL
# Service account: dsci-examplechurn-dev-composer@project.iam.gserviceaccount.com
```

After creation, note the DAGs folder GCS path and update `framework.yaml`.

### 9. Feature Store (Provision When Ready)

Bigtable-backed online serving costs ~$470/node/month. Feature Store resources (FeatureGroups, FeatureViews) are managed by the framework via `gml deploy --all`.

---

## Automated Bootstrap

`scripts/bootstrap.sh` automates the manual steps (2-6):

```bash
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project your-gcp-dev --env dev
```

---

## Terraform vs Framework Responsibilities

| Terraform (long-lived, shared) | Framework (ephemeral, per-branch) |
|-------------------------------|----------------------------------|
| Cloud Composer 3 environments | BQ datasets |
| Artifact Registry repos | GCS prefixes within buckets |
| GCS buckets | Vertex AI experiments, endpoints, models |
| IAM roles + service accounts | Composer DAG files |
| Workload Identity Federation | Feature Store resources |

---

## Checklist

- [ ] GCP projects created and billing linked (3 projects)
- [ ] APIs enabled in all projects
- [ ] GCS buckets created (or via Terraform)
- [ ] Artifact Registry repos created (or via Terraform)
- [ ] Service accounts + IAM roles configured (or via Terraform)
- [ ] Workload Identity Federation configured (if using GitHub Actions)
- [ ] GitHub secrets and variables set
- [ ] `framework.yaml` updated with actual project IDs
- [ ] `terraform validate` passes for all envs (if using Terraform)
- [ ] (When ready) Composer environment provisioned
- [ ] (When ready) `framework.yaml` updated with `composer_dags_path`
