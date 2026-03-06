#!/usr/bin/env bash
# seed_bq.sh — Load seed CSVs into BigQuery for GCP integration testing.
#
# Seeds are located in pipelines/{name}/seeds/*.csv. Each CSV maps to a raw
# table in the pipeline's BQ dataset. This script creates the dataset if needed
# and loads all seed files.
#
# Usage:
#   ./scripts/seed_bq.sh                              # uses framework.yaml + current branch
#   ./scripts/seed_bq.sh --dataset my_dataset          # override dataset name
#   ./scripts/seed_bq.sh --project gcp-gap-demo-dev    # override project

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Parse args
DATASET=""
PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dataset)  DATASET="$2"; shift 2 ;;
    --project)  PROJECT="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# Resolve from framework context if not provided
if [[ -z "$DATASET" ]] || [[ -z "$PROJECT" ]]; then
  CONTEXT=$(cd "$ROOT_DIR" && uv run gml context show --json 2>/dev/null | grep -v Warning)
  [[ -z "$DATASET" ]] && DATASET=$(echo "$CONTEXT" | python3 -c "import sys,json; print(json.load(sys.stdin)['bq_dataset'])")
  [[ -z "$PROJECT" ]] && PROJECT=$(echo "$CONTEXT" | python3 -c "import sys,json; print(json.load(sys.stdin)['gcp_project'])")
fi

echo "==> Seeding BQ dataset: ${PROJECT}:${DATASET}"

# Create dataset if it doesn't exist
bq mk --project_id="$PROJECT" --dataset "$DATASET" 2>/dev/null || true

# Find and load all seed CSVs
LOADED=0
for seed_dir in "$ROOT_DIR"/pipelines/*/seeds; do
  [[ -d "$seed_dir" ]] || continue
  pipeline_name=$(basename "$(dirname "$seed_dir")")

  for csv_file in "$seed_dir"/*.csv; do
    [[ -f "$csv_file" ]] || continue
    table_name=$(basename "$csv_file" .csv)

    echo "  Loading ${pipeline_name}/seeds/${table_name}.csv → ${DATASET}.${table_name}"
    bq load \
      --project_id="$PROJECT" \
      --source_format=CSV \
      --autodetect \
      --replace \
      "${DATASET}.${table_name}" \
      "$csv_file"

    LOADED=$((LOADED + 1))
  done
done

echo "==> Seed complete: ${LOADED} tables loaded into ${DATASET}"
