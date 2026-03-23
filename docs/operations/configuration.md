# Configuration Reference

## Environment Variables

All configuration is driven by environment variables, loaded from `.env` via `UV_ENV_FILE=.env`.

### Framework Variables (no prefix)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `TEAM` | Yes | Team identifier (slugified to max 12 chars) | `mlplatform` |
| `PROJECT` | Yes | Project name (slugified to max 20 chars) | `second_run` |
| `ENVIRONMENT` | Yes | Deployment environment: `local`, `dev`, `test`, `staging`, `prod`, `experiment` | `dev` |
| `BRANCH` | No | Git branch override. Auto-detected from git in local mode. | `feature/my-work` |

### GCP Variables (GCP_ prefix)

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `GCP_PROJECT_ID` | Yes | GCP project ID (single project, not per-env) | `prj-my-sandbox` |
| `GCP_REGION` | Yes | GCP region for all resources | `us-east4` |
| `GCP_COMPOSER_DAGS_PATH` | For deploy/run | GCS path to Composer DAGs bucket | `gs://composer-bucket/dags` |
| `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL` | No | Override pipeline SA (blank = derive from naming) | `sa@project.iam.gserviceaccount.com` |
| `GCP_COMPOSER_ENVIRONMENT_NAME` | No | Override Composer env name (blank = derive from naming) | `mlplatform-second-run-dev` |

### Docker Build Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `GCP_AR_HOST` | For push | Artifact Registry hostname | `us-east4-docker.pkg.dev` |
| `GCP_AR_REPO` | For push | AR repository name | `mlplatform-second-run` |
| `IMAGE_TAG` | No | Tag override (default: `{branch}-{sha}`) | `v1.0.0` |

## Config Classes

### FrameworkConfig

**Source:** `gcp_ml_framework/config.py`

```python
class FrameworkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", ...)

    team: str           # from TEAM env var
    project: str        # from PROJECT env var
    branch: str         # from BRANCH env var, or auto-detected from git
    environment: str    # from ENVIRONMENT env var
    gcp: GCPConfig      # nested, reads GCP_* vars
    feature_store: FeatureStoreConfig
    secrets: SecretsConfig
```

Key points:
- `env_prefix=""` -- reads `TEAM`, `PROJECT`, `ENVIRONMENT` directly (no prefix)
- `branch` defaults to `get_git_branch()` if not set explicitly
- `gcp` is a nested `GCPConfig` that auto-loads `GCP_*` variables
- Resolution order: defaults < pipeline/config.yaml < env vars < CLI flags

### GCPConfig

```python
class GCPConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCP_", ...)

    project_id: str                       # GCP_PROJECT_ID
    region: str                           # GCP_REGION
    composer_dags_path: str = ""          # GCP_COMPOSER_DAGS_PATH
    pipeline_service_account_email: str = ""  # GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL
    composer_environment_name: str = ""   # GCP_COMPOSER_ENVIRONMENT_NAME
```

`env_prefix="GCP_"` strips the prefix when mapping to fields: `GCP_PROJECT_ID` maps to `project_id`.

### Loading Config

```python
from gcp_ml_framework.config import load_config

# Auto-load from env vars
cfg = load_config()

# With pipeline-specific YAML overrides
cfg = load_config(pipeline_yaml="pipelines/house_price/config.yaml")

# With explicit overrides (used by CLI)
cfg = load_config(branch="feature/xyz", environment="dev")
```

## .env File

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

```bash
# .env.example
TEAM=mlplatform
PROJECT=second_run
ENVIRONMENT=local

GCP_PROJECT_ID=your-gcp-project-id
GCP_REGION=us-east4

# Uncomment for deploy/run:
# GCP_COMPOSER_DAGS_PATH=gs://composer-bucket/dags
# GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL=sa@project.iam.gserviceaccount.com
```

**Loading:** All `gml` CLI commands load `.env` via `UV_ENV_FILE`:

```bash
UV_ENV_FILE=.env uv run -- gml compile --all
```

## NamingConvention

**Source:** `gcp_ml_framework/naming.py`

`NamingConvention` is the single source of truth for ALL GCP resource names. No resource name should ever be constructed outside this module.

### Namespace

The canonical namespace token is `{team}-{project}-{branch}`, with each segment slugified (lowercased, non-alphanumeric replaced with hyphens, truncated).

```python
nc = NamingConvention(team="mlplatform", project="second_run", branch="feature/my-work")
nc.namespace  # "mlplatform-second-run-feature-my-work"
```

### Derived Resource Names

| Resource | Method | Pattern | Example |
|----------|--------|---------|---------|
| GCS bucket | `gcs_bucket` | `{gcp_project}-{team}-{project}` | `prj-sandbox-mlplatform-second-run` |
| GCS prefix | `gcs_prefix` | `gs://{bucket}/{branch}/` | `gs://prj-sandbox-mlplatform-second-run/feature-my-work/` |
| GCS pipeline root | `gcs_pipeline_root(name)` | `{prefix}/pipelines/{name}` | `gs://.../feature-my-work/pipelines/training` |
| GCS model path | `gcs_model_path(name)` | `{prefix}/models/{name}/latest` | `gs://.../models/house-price/latest` |
| BQ dataset | `bq_dataset` | `{namespace_bq}` (underscores) | `mlplatform_second_run_feature_my_work` |
| BQ table | `bq_table(name)` | `{dataset}.{name}` | `mlplatform_second_run_feature_my_work.raw_houses` |
| Vertex pipeline | `vertex_pipeline_display_name(name)` | `{namespace}-{name}` | `mlplatform-second-run-feature-my-work-training` |
| Vertex experiment | `vertex_experiment(name)` | `{namespace}-{name}-exp` | `mlplatform-second-run-feature-my-work-training-exp` |
| Vertex model | `vertex_model_name(pipe, model)` | `{namespace}-{pipe}[-{model}]` | `mlplatform-second-run-main-training-house-price` |
| Vertex endpoint | `vertex_endpoint_name(pipe, model)` | `{namespace}-{pipe}[-{model}]-endpoint` | `...training-house-price-endpoint` |
| AR repo | `artifact_registry_repo(host, proj)` | `{host}/{proj}/{team}-{project}` | `us-east4-docker.pkg.dev/prj/mlplatform-second-run` |
| Docker image | `docker_image_name(pipe, stem)` | `{pipe}--{stem}` | `house-price--base` |
| Image tag | `image_tag(name)` | `{branch}-{sha}` | `feature-my-work-a1b2c3d` |
| DAG ID | `dag_id(name)` | `{namespace_bq}__{name}` | `mlplatform_second_run_main__training` |
| Feature store | `feature_store_id` | `{team}_{project}` | `mlplatform_second_run` |
| Secret name | `secret_name(key)` | `{namespace}-{key}` | `mlplatform-second-run-main-api-key` |

### Branch Isolation

Every branch gets its own namespace, which means isolated:
- BQ datasets
- GCS prefixes
- Vertex AI experiments and models
- Airflow DAG IDs
- Docker image tags

This allows multiple developers to work concurrently without resource conflicts.

## Environment Resolution

The `ENVIRONMENT` env var determines the deployment target. It is NOT derived from the git branch.

| Value | Usage |
|-------|-------|
| `local` | Development on local machine; `BRANCH` auto-detected from git |
| `dev` | Development environment on GCP |
| `test` | QA / testing environment |
| `staging` | Pre-production |
| `prod` | Production |
| `experiment` | Experimental deployments (treated as production for safety checks) |

`get_git_branch()` is used ONLY for resource naming (branch isolation), not for environment resolution. In non-local environments, the branch must be provided as an env var (typically by CI/CD).

## MLContext

**Source:** `gcp_ml_framework/context.py`

`MLContext` is the immutable runtime object passed to every component and DAG. No component should import `FrameworkConfig` directly.

### Creation

```python
from gcp_ml_framework.config import load_config
from gcp_ml_framework.context import MLContext

cfg = load_config()
ctx = MLContext.from_config(cfg)
```

### Key Properties

| Property | Type | Description |
|----------|------|-------------|
| `ctx.naming` | `NamingConvention` | All resource name derivation methods |
| `ctx.gcp_project` | `str` | Active GCP project ID |
| `ctx.region` | `str` | GCP region |
| `ctx.environment` | `Environment` | Enum: LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT |
| `ctx.artifact_registry_host` | `str` | Derived: `{region}-docker.pkg.dev` |
| `ctx.composer_dags_path` | `str` | GCS path for Composer DAGs |
| `ctx.pipeline_service_account` | `str` | SA email (explicit or derived from naming) |
| `ctx.namespace` | `str` | Shortcut for `ctx.naming.namespace` |
| `ctx.bq_dataset` | `str` | Shortcut for `ctx.naming.bq_dataset` |
| `ctx.gcs_prefix` | `str` | Shortcut for `ctx.naming.gcs_prefix` |
| `ctx.feature_store_id` | `str` | Shortcut for `ctx.naming.feature_store_id` |

### Derived Values

`MLContext.from_config()` derives:
- `artifact_registry_host` = `{region}-docker.pkg.dev`
- `composer_environment_name` = explicit override or `{team}-{project}-{environment}`
- `secret_prefix` = explicit override or `namespace`
- `pipeline_service_account` = explicit override or `{team}-{project}-{env}-pipeline@{gcp_project}.iam.gserviceaccount.com`

### Inspecting Context

```bash
UV_ENV_FILE=.env uv run -- gml context show
```

This prints the full `ctx.summary()` dict: team, project, branch, environment, all derived resource names.
