#!/usr/bin/env bash
# bootstrap.sh — one-time GCP project setup for the GCP ML Framework.
#
# Enables required APIs and creates the Artifact Registry repository.
# Service accounts and IAM are managed by Terraform (terraform/modules/iam/).
#
# Usage:
#   ./scripts/bootstrap.sh --project my-gcp-project-dev
#   ./scripts/bootstrap.sh --project my-gcp-project-staging

set -euo pipefail

PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "Usage: $0 --project GCP_PROJECT_ID"
  exit 1
fi

echo "==> Bootstrapping GCP project: $PROJECT"
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
  --location=us-central1 \
  --description="GCP ML Framework container images" \
  --project="$PROJECT" || echo "Repository already exists."

echo ""
echo "==> Bootstrap complete for $PROJECT"
echo "    APIs enabled (including compute.googleapis.com for Composer 3)"
echo "    AR repository: $REPO_NAME"
echo ""
echo "    Next steps:"
echo "    1. Run Terraform to create service accounts and infrastructure:"
echo "       cd terraform/envs/dev && terraform init && terraform apply"
echo "    2. Configure Docker auth:"
echo "       gcloud auth configure-docker us-central1-docker.pkg.dev"
