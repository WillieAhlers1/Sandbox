#!/usr/bin/env bash
# bootstrap.sh — one-time GCP project setup for the GCP ML Framework.
#
# Run this once per GCP project (dev, staging, prod) to enable APIs,
# create service accounts, and configure Workload Identity Federation.
#
# Usage:
#   ./scripts/bootstrap.sh --project my-gcp-project-dev --env dev
#   ./scripts/bootstrap.sh --project my-gcp-project-staging --env staging
#   ./scripts/bootstrap.sh --project my-gcp-project-prod --env prod

set -euo pipefail

PROJECT=""
ENV="dev"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --env)     ENV="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "Usage: $0 --project GCP_PROJECT_ID --env (dev|staging|prod)"
  exit 1
fi

echo "==> Bootstrapping GCP project: $PROJECT (env=$ENV)"
gcloud config set project "$PROJECT"

# ── Enable required APIs ──────────────────────────────────────────────────────
echo "==> Enabling APIs..."
gcloud services enable \
  aiplatform.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  composer.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project="$PROJECT"

# ── Create ML service account ─────────────────────────────────────────────────
SA_NAME="gcp-ml-framework-sa"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

echo "==> Creating service account: $SA_EMAIL"
gcloud iam service-accounts create "$SA_NAME" \
  --display-name="GCP ML Framework Service Account" \
  --project="$PROJECT" || echo "Service account already exists."

# Grant required roles
ROLES=(
  "roles/bigquery.dataEditor"
  "roles/bigquery.jobUser"
  "roles/storage.objectAdmin"
  "roles/aiplatform.user"
  "roles/secretmanager.secretAccessor"
  "roles/composer.worker"
)
for ROLE in "${ROLES[@]}"; do
  echo "  Granting $ROLE..."
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="$ROLE" \
    --quiet
done

# ── Workload Identity Federation (GitHub Actions) ────────────────────────────
# Replace these with your GitHub org/repo
GITHUB_ORG="${GITHUB_ORG:-your-org}"
GITHUB_REPO="${GITHUB_REPO:-your-repo}"
POOL_ID="github-pool"
PROVIDER_ID="github-provider"

echo "==> Setting up Workload Identity Federation for GitHub Actions..."
gcloud iam workload-identity-pools create "$POOL_ID" \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  --project="$PROJECT" || echo "Pool already exists."

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --project="$PROJECT" || echo "Provider already exists."

PROVIDER_RESOURCE="projects/$(gcloud projects describe $PROJECT --format='value(projectNumber)')/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"

gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${PROVIDER_RESOURCE}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}" \
  --project="$PROJECT"

# ── Artifact Registry ─────────────────────────────────────────────────────────
echo "==> Creating Artifact Registry repository..."
TEAM=$(grep "^team:" framework.yaml | awk '{print $2}')
PROJECT_NAME=$(grep "^project:" framework.yaml | awk '{print $2}')
REPO_NAME="${TEAM}-${PROJECT_NAME}"

gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location=us-central1 \
  --description="GCP ML Framework container images" \
  --project="$PROJECT" || echo "Repository already exists."

echo ""
echo "==> Bootstrap complete for $PROJECT ($ENV)"
echo "    Service account: $SA_EMAIL"
echo "    WIF provider:    $PROVIDER_RESOURCE"
echo ""
echo "    Add these to your GitHub repo secrets/vars:"
echo "    WIF_PROVIDER_${ENV^^}=$PROVIDER_RESOURCE"
echo "    SA_EMAIL_${ENV^^}=$SA_EMAIL"
echo "    GCP_PROJECT_ID_${ENV^^}=$PROJECT"
