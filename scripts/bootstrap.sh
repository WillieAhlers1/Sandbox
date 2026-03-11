#!/usr/bin/env bash
# bootstrap.sh — one-time GCP project setup for the GCP ML Framework.
#
# Enables required APIs and creates the Artifact Registry repository.
# Service accounts and IAM are managed by Terraform (terraform/modules/iam/).
#
# Usage:
#   ./scripts/bootstrap.sh --project my-gcp-project-dev
#   ./scripts/bootstrap.sh --project my-gcp-project-dev --region us-east4

set -euo pipefail

PROJECT=""
REGION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --region)  REGION="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "Usage: $0 --project GCP_PROJECT_ID [--region GCP_REGION]"
  exit 1
fi

# Resolve region: CLI flag > framework.yaml > default
if [[ -z "$REGION" ]]; then
  REGION=$(grep '^\s*region:' framework.yaml 2>/dev/null | head -1 | awk '{print $2}')
fi
REGION="${REGION:-us-central1}"

echo "==> Bootstrapping GCP project: $PROJECT (region: $REGION)"
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
  compute.googleapis.com \
  --project="$PROJECT"

# ── Artifact Registry ─────────────────────────────────────────────────────────
echo "==> Creating Artifact Registry repository..."
TEAM=$(grep "^team:" framework.yaml | awk '{print $2}')
PROJECT_NAME=$(grep "^project:" framework.yaml | awk '{print $2}')
REPO_NAME="${TEAM}-${PROJECT_NAME}"

gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location="$REGION" \
  --description="GCP ML Framework container images" \
  --project="$PROJECT" || echo "Repository already exists."

echo ""
echo "==> Bootstrap complete for $PROJECT"
echo "    Region: $REGION"
echo "    APIs enabled (including compute.googleapis.com for Composer 3)"
echo "    AR repository: $REPO_NAME"
echo ""
echo "    Next steps:"
echo "    1. Run Terraform to create service accounts and infrastructure:"
echo "       cd terraform/envs/dev && terraform init && terraform apply"
echo "    2. Configure Docker auth:"
echo "       gcloud auth configure-docker ${REGION}-docker.pkg.dev"
