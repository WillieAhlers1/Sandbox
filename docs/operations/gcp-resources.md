# GCP Resource Map

How the GCP ML Framework creates, names, and manages GCP resources.

Every resource name flows from `NamingConvention` in `gcp_ml_framework/naming.py`. The namespace token is:

```
{team}-{project}-{branch}
```

For examples throughout this doc, we use:

| Variable       | Value            |
|----------------|------------------|
| `TEAM`         | `mlplatform`     |
| `PROJECT`      | `second_run`     |
| `BRANCH`       | `feature-xyz`    |
| `GCP_PROJECT_ID` | `prj-my-sandbox` |
| `GCP_REGION`   | `us-east4`       |

Namespace: **`mlplatform-second-run-feature-xyz`**

---

## 1. Resource Map

```mermaid
graph TB
    subgraph "GCP Project: prj-my-sandbox"
        subgraph "Artifact Registry"
            AR_REPO["Repository<br/>mlplatform-second-run"]
            AR_BASE["base-python:tag"]
            AR_PIPE_BASE["{pipeline}--base:tag"]
            AR_PIPE_SERVE["{pipeline}--serve:tag"]
            AR_REPO --> AR_BASE
            AR_REPO --> AR_PIPE_BASE
            AR_REPO --> AR_PIPE_SERVE
        end

        subgraph "Cloud Storage"
            GCS_BUCKET["Bucket<br/>prj-my-sandbox-mlplatform-second-run"]
            GCS_BRANCH["/{branch}/"]
            GCS_PIPELINES["pipelines/{name}/pipeline.yaml"]
            GCS_RUNS["pipeline_runs/{name}/"]
            GCS_DATA["data/{stage}/{dataset}/"]
            GCS_MODELS["models/{name}/{version}/"]
            GCS_BUCKET --> GCS_BRANCH
            GCS_BRANCH --> GCS_PIPELINES
            GCS_BRANCH --> GCS_RUNS
            GCS_BRANCH --> GCS_DATA
            GCS_BRANCH --> GCS_MODELS
        end

        subgraph "BigQuery"
            BQ_DATASET["Dataset<br/>mlplatform_second_run_feature_xyz"]
            BQ_TABLES["Tables: raw, staging,<br/>processed, predictions"]
            BQ_FEAT["feat_{entity}_{group}"]
            BQ_DATASET --> BQ_TABLES
            BQ_DATASET --> BQ_FEAT
        end

        subgraph "Vertex AI"
            VA_PIPELINE["Pipeline Runs<br/>mlplatform-second-run-feature-xyz-{pipeline}"]
            VA_EXPERIMENT["Experiments<br/>mlplatform-second-run-feature-xyz-{pipeline}-exp"]
            VA_MODEL["Model Registry<br/>mlplatform-second-run-feature-xyz-{pipeline}-{model}"]
            VA_ENDPOINT["Endpoints<br/>...-{pipeline}-{model}-endpoint"]
            VA_MONITORING["Monitoring Jobs<br/>...-endpoint-monitoring"]
            VA_MODEL --> VA_ENDPOINT
            VA_ENDPOINT --> VA_MONITORING
        end

        subgraph "Feature Store v2"
            FS_STORE["FeatureOnlineStore<br/>mlplatform_second_run"]
            FS_GROUP["FeatureGroups<br/>{entity}_{group}"]
            FS_VIEW["FeatureViews<br/>{entity}_{group}_{branch}"]
            FS_STORE --> FS_VIEW
            FS_GROUP --> FS_VIEW
        end

        subgraph "Cloud Composer"
            COMPOSER_ENV["Environment<br/>mlplatform-second-run-dev"]
            COMPOSER_DAGS["DAGs Bucket<br/>gs://composer-bucket/dags/"]
            DAG_FILE["{namespace}__{pipeline}.py"]
            COMPOSER_ENV --> COMPOSER_DAGS
            COMPOSER_DAGS --> DAG_FILE
        end

        subgraph "Cloud Build"
            CB["Build Jobs<br/>cloudbuild.yaml"]
            CB --> AR_REPO
        end

        subgraph "Secret Manager"
            SM["Secrets<br/>mlplatform-second-run-feature-xyz-{key}"]
        end
    end
```

---

## 2. Naming Convention Table

All names are derived by `NamingConvention` (`gcp_ml_framework/naming.py`). The `_slugify()` function lowercases, replaces non-alphanumeric runs with hyphens, and truncates. `_bq_safe()` uses underscores instead (BigQuery requirement).

| Resource | Method | Derived Name |
|----------|--------|-------------|
| **Namespace** | `namespace` | `mlplatform-second-run-feature-xyz` |
| **BQ Namespace** | `namespace_bq` | `mlplatform_second_run_feature_xyz` |
| **GCS Bucket** | `gcs_bucket` | `prj-my-sandbox-mlplatform-second-run` |
| **GCS Prefix** | `gcs_prefix` | `gs://prj-my-sandbox-mlplatform-second-run/feature-xyz/` |
| **GCS Pipeline Root** | `gcs_pipeline_root("training")` | `.../feature-xyz/pipelines/training` |
| **GCS Data Path** | `gcs_data_path("raw", "sales")` | `.../feature-xyz/data/raw/sales` |
| **GCS Model Path** | `gcs_model_path("regression")` | `.../feature-xyz/models/regression/latest` |
| **BQ Dataset** | `bq_dataset` | `mlplatform_second_run_feature_xyz` |
| **BQ Table** | `bq_table("predictions")` | `mlplatform_second_run_feature_xyz.predictions` |
| **BQ Feature Table** | `bq_feature_table("user", "behavioral")` | `mlplatform_second_run_feature_xyz.feat_user_behavioral` |
| **Vertex Pipeline** | `vertex_pipeline_display_name("training")` | `mlplatform-second-run-feature-xyz-training` |
| **Vertex Experiment** | `vertex_experiment("training")` | `mlplatform-second-run-feature-xyz-training-exp` |
| **Vertex Model** | `vertex_model_name("training", "regression")` | `mlplatform-second-run-feature-xyz-training-regression` |
| **Vertex Endpoint** | `vertex_endpoint_name("training", "regression")` | `mlplatform-second-run-feature-xyz-training-regression-endpoint` |
| **Vertex Training Job** | `vertex_training_job_name("train_hp")` | `mlplatform-second-run-feature-xyz-train-hp` |
| **AR Repo** | `artifact_registry_repo(host, proj)` | `us-east4-docker.pkg.dev/prj-my-sandbox/mlplatform-second-run` |
| **Docker Image Name** | `docker_image_name("house_price", "base")` | `house-price--base` |
| **Image Tag** | `image_tag("img")` | `feature-xyz-a1b2c3d` |
| **Image URI** | `docker_image_uri(...)` | `us-east4-docker.pkg.dev/prj-my-sandbox/mlplatform-second-run/house-price--base:feature-xyz-a1b2c3d` |
| **Feature Store ID** | `feature_store_id` | `mlplatform_second_run` |
| **Feature View** | `feature_view_id("user", "behavioral")` | `user_behavioral_feature_xyz` |
| **DAG ID** | `dag_id("training")` | `mlplatform_second_run_feature_xyz__training` |
| **Secret Name** | `secret_name("db-password")` | `mlplatform-second-run-feature-xyz-db-password` |
| **Composer Env** | derived in `MLContext` | `mlplatform-second-run-dev` |
| **Pipeline SA** | derived in `MLContext` | `mlplatform-second-run-dev-pipeline@prj-my-sandbox.iam.gserviceaccount.com` |

---

## 3. Branch Isolation

Different branches get their own isolated namespaces for data and compute resources, while sharing the Artifact Registry repository and GCS bucket.

```mermaid
graph TB
    subgraph "SHARED across all branches"
        GCS_BUCKET["GCS Bucket<br/>prj-my-sandbox-mlplatform-second-run"]
        AR_REPO["AR Repository<br/>us-east4-docker.pkg.dev/prj-my-sandbox/mlplatform-second-run"]
        FS_STORE["FeatureOnlineStore<br/>mlplatform_second_run"]
    end

    subgraph "Branch: main"
        GCS_MAIN["GCS: .../main/pipelines/<br/>.../main/models/<br/>.../main/data/"]
        BQ_MAIN["BQ Dataset:<br/>mlplatform_second_run_main"]
        DAG_MAIN["DAG: mlplatform_second_run_main__training"]
        VTX_MAIN["Vertex Experiment:<br/>...-main-training-exp"]
        MODEL_MAIN["Vertex Model:<br/>...-main-training-regression"]
        EP_MAIN["Vertex Endpoint:<br/>...-main-training-regression-endpoint"]
        FV_MAIN["FeatureView:<br/>user_behavioral_main"]
        SECRET_MAIN["Secret:<br/>...-main-db-password"]
    end

    subgraph "Branch: feature-xyz"
        GCS_FEAT["GCS: .../feature-xyz/pipelines/<br/>.../feature-xyz/models/<br/>.../feature-xyz/data/"]
        BQ_FEAT["BQ Dataset:<br/>mlplatform_second_run_feature_xyz"]
        DAG_FEAT["DAG: mlplatform_second_run_feature_xyz__training"]
        VTX_FEAT["Vertex Experiment:<br/>...-feature-xyz-training-exp"]
        MODEL_FEAT["Vertex Model:<br/>...-feature-xyz-training-regression"]
        EP_FEAT["Vertex Endpoint:<br/>...-feature-xyz-training-regression-endpoint"]
        FV_FEAT["FeatureView:<br/>user_behavioral_feature_xyz"]
        SECRET_FEAT["Secret:<br/>...-feature-xyz-db-password"]
    end

    GCS_BUCKET --> GCS_MAIN
    GCS_BUCKET --> GCS_FEAT
    AR_REPO --> |"images tagged<br/>main-a1b2c3d"| BQ_MAIN
    AR_REPO --> |"images tagged<br/>feature-xyz-d4e5f6g"| BQ_FEAT
    FS_STORE --> FV_MAIN
    FS_STORE --> FV_FEAT
```

### What is shared vs. isolated

| Resource | Shared or Isolated | Isolation Key |
|----------|-------------------|---------------|
| GCS Bucket | **Shared** | Branch is a path prefix (`/{branch}/`) |
| AR Repository | **Shared** | Branch is in the image tag (`{branch}-{sha}`) |
| Feature Online Store | **Shared** | Branch is in the FeatureView ID |
| BQ Dataset | **Isolated** | Full dataset name includes branch |
| Vertex AI Experiments | **Isolated** | Display name includes branch |
| Vertex AI Models | **Isolated** | Display name includes branch |
| Vertex AI Endpoints | **Isolated** | Display name includes branch |
| Composer DAGs | **Isolated** | DAG ID includes branch |
| Secret Manager | **Isolated** | Secret name includes branch |
| Feature Views | **Isolated** | View ID includes branch |

---

## 4. IAM Relationships

```mermaid
graph LR
    subgraph "Service Accounts"
        DEV_SA["Developer<br/>(your GCP identity)"]
        PIPELINE_SA["Pipeline SA<br/>mlplatform-second-run-dev-pipeline@..."]
        COMPOSER_SA["Composer SA<br/>(managed by Composer)"]
        CB_SA["Cloud Build SA<br/>(or Pipeline SA)"]
    end

    subgraph "GCP Resources"
        AR["Artifact Registry"]
        GCS["Cloud Storage"]
        BQ["BigQuery"]
        VERTEX["Vertex AI"]
        COMPOSER["Cloud Composer"]
        SM["Secret Manager"]
        FS["Feature Store"]
    end

    DEV_SA -->|"gml build<br/>gml deploy<br/>gml run"| COMPOSER
    DEV_SA -->|"gml compile<br/>(local only)"| GCS

    CB_SA -->|"builds + pushes<br/>Docker images"| AR
    CB_SA -->|"reads source"| GCS

    COMPOSER_SA -->|"triggers DAGs<br/>impersonates Pipeline SA"| VERTEX
    COMPOSER_SA -->|"reads DAG files"| GCS

    PIPELINE_SA -->|"runs pipelines"| VERTEX
    PIPELINE_SA -->|"reads/writes data"| BQ
    PIPELINE_SA -->|"reads/writes artifacts"| GCS
    PIPELINE_SA -->|"pulls images"| AR
    PIPELINE_SA -->|"reads secrets"| SM
    PIPELINE_SA -->|"manages features"| FS
```

### Required IAM Roles

| Service Account | Required Roles | Purpose |
|----------------|---------------|---------|
| **Pipeline SA** | `roles/aiplatform.user` | Run Vertex AI pipelines, manage models and endpoints |
| | `roles/bigquery.dataEditor` | Read/write BQ datasets and tables |
| | `roles/storage.objectAdmin` | Read/write GCS objects (models, data, pipeline YAML) |
| | `roles/artifactregistry.reader` | Pull container images during pipeline execution |
| | `roles/secretmanager.secretAccessor` | Read secrets at runtime |
| | `roles/aiplatform.featurestoreUser` | Read/write Feature Store v2 resources |
| **Composer SA** | `roles/composer.worker` | Run Airflow workers |
| | `roles/iam.serviceAccountUser` on Pipeline SA | Impersonate Pipeline SA when launching Vertex AI jobs |
| **Cloud Build SA** | `roles/artifactregistry.writer` | Push Docker images |
| | `roles/storage.objectViewer` | Read build context |
| | `roles/logging.logWriter` | Write build logs |
| **Developer** | `roles/composer.user` | Trigger DAGs via `gml run` |
| | `roles/cloudbuild.builds.editor` | Submit builds via `gml build` |
| | `roles/storage.objectAdmin` | Upload DAGs and pipeline YAML via `gml deploy` |

### Composer-to-Pipeline SA Impersonation

The generated Airflow DAG uses `RunPipelineJobOperator` with `service_account` set to the Pipeline SA email. Cloud Composer's own service account must have `roles/iam.serviceAccountUser` on the Pipeline SA to launch Vertex AI pipeline runs under that identity.

```
Composer SA  --[iam.serviceAccountUser]-->  Pipeline SA  --[aiplatform.user]--> Vertex AI
```

---

## 5. Data Flow Through GCP

End-to-end flow from raw data to a deployed model endpoint.

```mermaid
flowchart LR
    subgraph "1. Data Ingestion"
        RAW_BQ["Raw Data<br/>in BigQuery"]
    end

    subgraph "2. Transformation"
        BQ_QUERY["BQQuery / BQTransform<br/>(@task - Airflow operator)"]
        STAGING_BQ["Staging/Processed<br/>BQ Tables"]
        RAW_BQ --> BQ_QUERY --> STAGING_BQ
    end

    subgraph "3. Feature Engineering"
        FEAT_TABLE["Feature Tables<br/>feat_{entity}_{group}"]
        FEAT_GROUP["FeatureGroup<br/>(metadata registration)"]
        FEAT_VIEW["FeatureView<br/>(online serving sync)"]
        STAGING_BQ --> FEAT_TABLE
        FEAT_TABLE --> FEAT_GROUP --> FEAT_VIEW
    end

    subgraph "4. Training"
        TRAIN["TrainModel<br/>(@ml_task - Vertex AI)"]
        GCS_MODEL["Model Artifacts<br/>gs://.../models/{name}/latest/"]
        EXPERIMENT["Vertex AI Experiment<br/>params + metrics logged"]
        STAGING_BQ --> TRAIN
        TRAIN --> GCS_MODEL
        TRAIN --> EXPERIMENT
    end

    subgraph "5. Evaluation"
        EVAL["EvaluateModel<br/>(@ml_task)"]
        GATE{"Metric Gate<br/>Pass?"}
        GCS_MODEL --> EVAL
        EVAL --> GATE
    end

    subgraph "6. Registration"
        REGISTER["RegisterModel<br/>(@ml_task)"]
        MODEL_REG["Vertex AI<br/>Model Registry"]
        SERVE_IMG["Serving Container<br/>{pipeline}--serve"]
        GATE -->|"Yes"| REGISTER
        GCS_MODEL --> REGISTER
        SERVE_IMG --> REGISTER
        REGISTER --> MODEL_REG
    end

    subgraph "7. Deployment"
        DEPLOY["DeployModel<br/>(@ml_task)"]
        ENDPOINT["Vertex AI Endpoint<br/>...-endpoint"]
        MONITORING["Model Monitoring<br/>(optional)"]
        MODEL_REG --> DEPLOY --> ENDPOINT
        ENDPOINT --> MONITORING
    end
```

### Detailed Data Locations at Each Stage

| Stage | Location | Example Path |
|-------|----------|-------------|
| Raw data | BigQuery (external) | `prj-my-sandbox.raw_data.house_sales` |
| Transformed data | BQ dataset (branch-scoped) | `prj-my-sandbox.mlplatform_second_run_feature_xyz.processed_sales` |
| Feature tables | BQ dataset (branch-scoped) | `prj-my-sandbox.mlplatform_second_run_feature_xyz.feat_house_behavioral` |
| Model artifacts | GCS (branch-scoped) | `gs://prj-my-sandbox-mlplatform-second-run/feature-xyz/models/regression/latest/model.pkl` |
| Compiled pipeline | GCS (branch-scoped) | `gs://prj-my-sandbox-mlplatform-second-run/feature-xyz/pipelines/training/pipeline.yaml` |
| Pipeline run artifacts | GCS (branch-scoped) | `gs://prj-my-sandbox-mlplatform-second-run/feature-xyz/pipeline_runs/training/` |
| Registered model | Vertex AI Model Registry | `mlplatform-second-run-feature-xyz-training-regression` (display name) |
| Deployed model | Vertex AI Endpoint | `mlplatform-second-run-feature-xyz-training-regression-endpoint` |
| DAG file | Composer GCS bucket | `gs://composer-bucket/dags/mlplatform_second_run_feature_xyz__training.py` |

---

## 6. Docker Image Hierarchy

Cloud Build (`cloudbuild.yaml`) builds images in a three-tier hierarchy with layer caching.

```mermaid
flowchart TB
    BASE["Tier 0: base-python<br/>docker/base/base-python/Dockerfile<br/>Shared Python foundation"]
    PIPE_BASE["Tier 1: {pipeline}--base<br/>docker/pipelines/{name}/base.Dockerfile<br/>Pipeline execution image<br/>(runtime_dockerfile)"]
    PIPE_SERVE["Tier 1: {pipeline}--serve<br/>docker/pipelines/{name}/serve.Dockerfile<br/>Pipeline serving image<br/>(serving_dockerfile)"]

    BASE --> PIPE_BASE
    PIPE_BASE --> PIPE_SERVE

    style BASE fill:#e1f5fe
    style PIPE_BASE fill:#fff3e0
    style PIPE_SERVE fill:#e8f5e9
```

### Image Naming Convention

`NamingConvention.docker_image_name()` uses the `--` delimiter to scope images to pipelines:

| Dockerfile Location | `docker_image_name()` | Full AR URI |
|---------------------|-----------------------|-------------|
| `docker/base/base-python/Dockerfile` | `base-python` | `.../mlplatform-second-run/base-python:feature-xyz-a1b2c3d` |
| `docker/pipelines/house_price/base.Dockerfile` | `house-price--base` | `.../mlplatform-second-run/house-price--base:feature-xyz-a1b2c3d` |
| `docker/pipelines/house_price/serve.Dockerfile` | `house-price--serve` | `.../mlplatform-second-run/house-price--serve:feature-xyz-a1b2c3d` |

### Image Tag Format

Tags encode traceability: `{branch_slug}-{short_sha}`

- `feature-xyz-a1b2c3d` -- you can trace any running container back to the exact commit and branch.
- Cloud Build also pushes `:latest` for layer cache warm-starts on subsequent builds.

---

## 7. GCS Bucket Layout

The GCS bucket is shared across branches. Each branch gets its own prefix.

```
gs://prj-my-sandbox-mlplatform-second-run/
  feature-xyz/
    pipelines/
      training/
        pipeline.yaml          # Compiled KFP YAML
      house_price/
        pipeline.yaml
    pipeline_runs/
      training/                # Vertex AI pipeline run artifacts
    data/
      raw/
        sales/
      staging/
        processed_sales/
      processed/
      features/
    models/
      regression/
        latest/
          model.pkl
          metadata.json
  main/
    pipelines/...
    models/...
    data/...
```

---

## 8. Secret Manager Naming

Secrets are branch-namespaced so DEV, STAGING, and PROD can have independent values for the same logical key.

```
Short key:    db-password
Namespace:    mlplatform-second-run-feature-xyz
Secret name:  mlplatform-second-run-feature-xyz-db-password
Resource:     projects/prj-my-sandbox/secrets/mlplatform-second-run-feature-xyz-db-password/versions/latest
```

In local development, `LocalSecretClient` reads from environment variables instead:

```
GML_SECRET_DB_PASSWORD=my-local-value
```

---

## 9. Resource Lifecycle Summary

```mermaid
stateDiagram-v2
    [*] --> Created: gml compile / gml deploy
    Created --> Active: Pipeline runs successfully
    Active --> Active: Subsequent pipeline runs
    Active --> Torn_Down: gml teardown --branch feature-xyz

    state Created {
        [*] --> DAG_Uploaded: DAG to Composer bucket
        [*] --> YAML_Uploaded: Pipeline YAML to GCS
        [*] --> Images_Built: Docker images to AR
    }

    state Active {
        [*] --> BQ_Dataset: Created on first write
        [*] --> GCS_Objects: Pipeline artifacts accumulate
        [*] --> Vertex_Resources: Experiments, models, endpoints
        [*] --> Feature_Views: Online serving synced
    }

    state Torn_Down {
        [*] --> GCS_Deleted: Objects under branch prefix
        [*] --> BQ_Deleted: Branch dataset dropped
        [*] --> DAGs_Deleted: DAG files + Airflow metadata
        note right of GCS_Deleted: AR images are NOT deleted\n(shared repo, immutable tags)
    }
```

`gml teardown` only runs for DEV branches -- it will refuse to touch STAGING or PROD. It deletes:

1. GCS objects under `gs://{bucket}/{branch}/`
2. BigQuery dataset `{namespace_bq}`
3. Composer DAG files matching `{namespace_bq}__*`
4. Airflow metadata for those DAGs

It does **not** delete: AR images, Vertex AI models/endpoints (manual cleanup), or Feature Store online stores.
