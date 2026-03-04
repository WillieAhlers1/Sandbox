# Terraform - Infrastructure as Code for churn_prediction_new Pipeline

Automatic provisioning of GCP resources for the churn_prediction_new pipeline.

## How It Works

This Terraform configuration is **automatically executed** when you run:

```bash
gml run churn_prediction_new --vertex --sync
```

The pipeline execution follows this sequence:

1. **Terraform Apply** (First step - automatic)
   - Creates BigQuery dataset
   - **Executes ALL SQL files** from `sql/BQ/` folder
   - Creates Artifact Registry
   - Sets up Cloud Build triggers
   - Grants IAM permissions

2. **Docker Build** (Automatic)
   - Builds trainer container from Dockerfile
   - Pushes to Artifact Registry

3. **KFP Compilation** (Automatic)
   - Compiles pipeline.py to Vertex AI format

4. **Pipeline Submission** (Automatic)
   - Submits to Vertex AI Pipelines
   - Waits for completion (--sync)

## SQL File Execution

The key feature: **SQL files are executed dynamically at runtime**.

### How SQL Discovery Works

Terraform automatically discovers and executes:
- **All files** in `sql/BQ/*.sql` → Creates tables
- **All files** in `sql/FS/*.sql` → Creates Feature Store entities

You can:
- ✅ Add new SQL files → Automatically executed
- ✅ Rename SQL files → Still executed
- ✅ Remove SQL files → No error, just skipped
- ✅ Modify SQL content → Changes applied on next run

### Example

If you have these files:
```
sql/BQ/
├── raw_data.sql                    ← Auto-executed
├── daily_features.sql              ← Auto-executed
└── metrics.sql                     ← Auto-executed

sql/FS/
└── user_entity.sql                 ← Auto-executed
```

Running `gml run churn_prediction_new` will execute all 4 files with no additional configuration needed.

## Manual Terraform Operations

For debugging or testing, you can run Terraform directly:

### Initialize
```bash
cd terraform
terraform init
```

### Plan (see what will happen)
```bash
terraform plan
```

### Apply Manually
```bash
terraform apply
```

(Usually not needed - `gml run` does this automatically)

### Destroy (clean up)
```bash
terraform destroy
```

## Configuration

Edit `terraform.tfvars` with your GCP details:

```hcl
project_id                = "prj-0n-dta-pt-ai-sandbox"
region                    = "us-east4"
bigquery_dataset_id       = "dsci_churn_prediction_new_main"
github_owner              = "your-github-org"
github_repo               = "your-github-repo"
git_branch                = "main"
service_account_email     = "gc-sa-xxx@prj-xxx.iam.gserviceaccount.com"
enable_feature_store      = true
featurestore_node_count   = 1

common_labels = {
  team    = "dsci"
  project = "churn_prediction_new"
  env     = "dev"
}
```

## Cost Tracking

All resources are labeled with `pipeline = "churn_prediction_new"` and `managed_by = "terraform"`.

View costs:
```bash
gcloud billing accounts list
gcloud compute project-info describe PROJECT_ID \
  --format='value(labels.pipeline)'
```

## Troubleshooting

### SQL Execution Failed
Check the SQL syntax in your files:
```bash
# Validate locally
bq query --use_legacy_sql=false < sql/BQ/raw_data.sql --dry_run
```

### Terraform State Issues
If state gets corrupted:
```bash
rm -rf .terraform .terraform.lock.hcl terraform.tfstate*
terraform init
terraform apply
```

### Permission Denied
Ensure service account has roles:
- roles/bigquery.admin
- roles/aiplatform.admin
- roles/artifactregistry.admin

## Next Steps

1. **Customize SQL files** in `sql/BQ/` and `sql/FS/`
2. **Edit pipeline.py** to define your workflow
3. **Update trainer.py** with your model code
4. **Run pipeline**: `gml run churn_prediction_new --vertex --sync`

---

**Important**: 
- ✅ terraform.tfvars **auto-created** from framework.yaml
- ✅ `gml run churn_prediction_new --vertex --sync` runs **terraform apply -auto-approve** (no prompts)
- ✅ All SQL files in sql/BQ/ and sql/FS/ execute automatically
- 📝 Only customize terraform.tfvars if you need non-standard values
