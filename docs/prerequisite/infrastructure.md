# Infrastructure Setup

> One-time setup per GCP project. Run for each environment (DEV, STAGING, PROD).

## Prerequisites

- Google Cloud billing account linked to all projects
- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- Owner role on each project

## 1. Create GCP Projects

```bash
gcloud projects create gcp-gap-demo-dev --name="GCP GAP Demo Dev"
gcloud projects create gcp-gap-demo-staging --name="GCP GAP Demo Staging"
gcloud projects create gcp-gap-demo-prod --name="GCP GAP Demo Prod"

# Link billing
gcloud billing projects link gcp-gap-demo-dev --billing-account=BILLING_ACCOUNT_ID
gcloud billing projects link gcp-gap-demo-staging --billing-account=BILLING_ACCOUNT_ID
gcloud billing projects link gcp-gap-demo-prod --billing-account=BILLING_ACCOUNT_ID
```

## 2. Enable APIs

Run for each project:

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
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

## 3. Create GCS Bucket

One bucket per team+project. Branches share the bucket via path prefixes.

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  gsutil mb -p "${PROJECT}" -l us-central1 -c standard "gs://dsci-example-churn-${PROJECT##*-}/"
done
```

Settings: Region `us-central1`, Standard class, Uniform access control.

## 4. Create Artifact Registry

One Docker repo per team+project.

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  gcloud artifacts repositories create dsci-example-churn \
    --repository-format=docker \
    --location=us-central1 \
    --project="${PROJECT}"
done
```

## 5. Create Service Account + IAM Roles

```bash
for PROJECT in gcp-gap-demo-dev gcp-gap-demo-staging gcp-gap-demo-prod; do
  SA_NAME="gcp-ml-framework-sa"
  SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="ML Framework pipeline service account" \
    --project="${PROJECT}"

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

## 6. Configure Workload Identity Federation (GitHub Actions)

```bash
PROJECT=gcp-gap-demo-dev  # repeat for each project

# Create pool
gcloud iam workload-identity-pools create github-pool \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  --project="${PROJECT}"

# Add OIDC provider
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="${PROJECT}"

# Bind to GitHub repo
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
SA_EMAIL="gcp-ml-framework-sa@${PROJECT}.iam.gserviceaccount.com"

gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/YOUR_ORG/YOUR_REPO" \
  --project="${PROJECT}"
```

## 7. Set GitHub Repository Secrets

| Secret | Value |
|---|---|
| `WIF_PROVIDER_DEV` | `projects/{NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `WIF_PROVIDER_STAGING` | Same pattern for staging project |
| `WIF_PROVIDER_PROD` | Same pattern for prod project |
| `SA_EMAIL_DEV` | `gcp-ml-framework-sa@gcp-gap-demo-dev.iam.gserviceaccount.com` |
| `SA_EMAIL_STAGING` | `gcp-ml-framework-sa@gcp-gap-demo-staging.iam.gserviceaccount.com` |
| `SA_EMAIL_PROD` | `gcp-ml-framework-sa@gcp-gap-demo-prod.iam.gserviceaccount.com` |

Set as GitHub repo variables:

| Variable | Value |
|---|---|
| `GCP_PROJECT_ID_DEV` | `gcp-gap-demo-dev` |
| `GCP_PROJECT_ID_STAGING` | `gcp-gap-demo-staging` |
| `GCP_PROJECT_ID_PROD` | `gcp-gap-demo-prod` |

## 8. Cloud Composer (Defer Until Needed)

Composer costs ~$300-500/month. Provision only when scheduled DAG execution is required.

```bash
# When ready:
# Navigate to Composer in GCP Console → Create Environment → Composer 2
# Name: ml-composer-env, Region: us-central1
# Add env vars: GML_TEAM, GML_PROJECT, GML_GCP__REGION
```

After creation, note the DAGs folder GCS path from the Environment Configuration tab.

## 9. Feature Store (Defer Until Needed)

Bigtable-backed online serving costs ~$470/node/month. Provision only when online serving is needed.

Feature Store resources and feature views are managed by `gml deploy features`.

## Automated Bootstrap

`scripts/bootstrap.sh` automates steps 2-6:

```bash
GITHUB_ORG=your-org GITHUB_REPO=your-repo \
  ./scripts/bootstrap.sh --project gcp-gap-demo-dev --env dev
```

## Checklist

- [ ] 3 GCP projects created and billing linked
- [ ] APIs enabled in all projects
- [ ] GCS buckets created
- [ ] Artifact Registry repos created
- [ ] Service accounts + IAM roles configured
- [ ] Workload Identity Federation configured
- [ ] GitHub secrets and variables set
- [ ] `framework.yaml` updated with actual project IDs
- [ ] (When needed) Composer environment provisioned
- [ ] (When needed) Feature Store provisioned
