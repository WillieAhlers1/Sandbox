# Cloud Build IAM Requirements

## Required Roles

The Cloud Build service account needs these IAM roles:

| Role | Purpose |
|------|---------|
| `roles/artifactregistry.writer` | Push Docker images to Artifact Registry |
| `roles/storage.objectAdmin` | Read/write to GCS buckets (pipeline artifacts, DAGs) |
| `roles/logging.logWriter` | Write build logs to Cloud Logging |

## Granting Roles

```bash
# Get the Cloud Build SA email
PROJECT_ID="your-project-id"
CB_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"

# Grant AR write access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/artifactregistry.writer"

# Grant GCS access
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/storage.objectAdmin"
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `FAILED_PRECONDITION` on AR push | Cloud Build SA lacks `artifactregistry.writer` | Grant the role above |
| `403 Access Denied` on GCS | Cloud Build SA lacks `storage.objectAdmin` | Grant the role above |
| `Permission denied` on `gcloud builds submit` | User lacks `cloudbuild.builds.create` | `gcloud projects add-iam-policy-binding ... --role="roles/cloudbuild.builds.editor"` |

## Notes
- Terraform manages IAM in production environments — these manual commands are for dev/sandbox setup
- The default Cloud Build SA (`{project-number}@cloudbuild.gserviceaccount.com`) is different from the Compute Engine SA
- In enterprise environments with VPC SC, additional network permissions may be required
