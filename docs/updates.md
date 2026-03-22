# GML Framework — Change Log

---

## 1.0 [P1] Simplify GCPConfig to Single Project ID + Region

**Problem:** `GCPConfig` carried per-environment project IDs (`dev_project_id`, `staging_project_id`, `prod_project_id`, `test_project_id`) and several infrastructure fields (`composer_dags_path`, `composer_environment_name`, `pipeline_service_account_email`, `artifact_registry_host`). This forced every `.env` file to define multiple `GML_GCP__*_PROJECT_ID` variables even though CI/CD already sets the correct project ID for a given environment. It also coupled framework config to infrastructure details that should be derived or managed externally.

**Solution:** Reduce `GCPConfig` to two fields: `project_id` and `region`. CI/CD sets the right values per environment. All other resource identifiers (AR host, Composer env name, pipeline SA email) are derived at runtime from team/project/region naming conventions.

**Changes:**

- `gcp_ml_framework/config.py`:
  - `GCPConfig`: Removed `dev_project_id`, `staging_project_id`, `prod_project_id`, `test_project_id`, `composer_dags_path`, `artifact_registry_host`, `pipeline_service_account_email`, `composer_environment_name`, and the `_derive_ar_host` validator. Retained only `project_id` and `region`.
  - `GCPConfig`: Changed from `BaseModel` to `BaseSettings` with `env_prefix="GCP_"` so it reads `GCP_PROJECT_ID` and `GCP_REGION` directly from environment.
  - `FrameworkConfig._validate_projects`: Removed entirely (no per-env project IDs to validate).
  - `FrameworkConfig.active_gcp_project`: Simplified to return `self.gcp.project_id`.
  - `FrameworkConfig`: Changed `env_prefix` from `"GML_"` to `""` and added `populate_by_name=True` so env vars `TEAM`, `PROJECT`, `ENVIRONMENT`, `BRANCH` are read directly.
- `gcp_ml_framework/context.py` (`MLContext`):
  - `artifact_registry_host`: Now derived from region (`f"{region}-docker.pkg.dev"`) instead of reading from config.
  - `composer_environment_name`: Now derived from naming (`f"{team}-{project}-{env}"`) instead of reading from config.
  - `composer_dags_path`: Defaults to empty dict (Composer path is set when Composer is provisioned).
  - `pipeline_service_account_email`: Removed as a stored field. The `pipeline_service_account` property now always derives the SA email from naming convention (`{team}-{project}-{env}-pipeline@{project}.iam.gserviceaccount.com`).
- `gcp_ml_framework/cli/cmd_build.py`:
  - Replaced `ctx.pipeline_service_account_email` with `ctx.pipeline_service_account` (the derived property).
- `.env`:
  - Replaced `GML_GCP__DEV_PROJECT_ID`, `GML_GCP__STAGING_PROJECT_ID`, `GML_GCP__PROD_PROJECT_ID` with single `GCP_PROJECT_ID`.
  - Replaced `GML_GCP__REGION` / `GML_REGION` with `GCP_REGION`.
  - Replaced `GML_TEAM`, `GML_PROJECT`, `GML_ENVIRONMENT` with `TEAM`, `PROJECT`, `ENVIRONMENT`.
  - Added `BRANCH` (defaults to git branch if not set).

---

## 4.0 [P2] Docker Build Pipeline Fix — uv sync Flag

**Problem:** The pipeline Dockerfile used `uv sync --all --frozen`, but newer versions of `uv` removed the `--all` flag, causing Docker builds to fail.

**Solution:** Updated the flag to `--all-groups`, which is the correct replacement.

**Changes:**

- `docker/pipeline/Dockerfile`: Changed `RUN uv sync --all --frozen` to `RUN uv sync --all-groups --frozen`.

---

## 5.0 [P2] Artifact Registry Repository and GCS Bucket Provisioning

**Problem:** `gml deploy` and `docker_build.sh --push` failed because the Artifact Registry repository (`mlplatform-third-run`) and GCS bucket (`prj-0n-dta-pt-ai-sandbox-mlplatform-third-run`) did not exist in the target GCP project.

**Solution:** Created the missing resources manually. Long-term these should be provisioned via Terraform.

**Changes:**

- Created AR repository: `gcloud artifacts repositories create mlplatform-third-run --repository-format=docker --location=us-east4 --project=prj-0n-dta-pt-ai-sandbox`
- Created GCS bucket: `gcloud storage buckets create gs://prj-0n-dta-pt-ai-sandbox-mlplatform-third-run --project=prj-0n-dta-pt-ai-sandbox --location=us-east4`

---

## 6.0 [P3] Docker Build Script and .env Variable Alignment

**Problem:** `docker_build.sh` reads `AR_HOST`, `GCP_PROJECT`, and `AR_REPO` environment variables, but after the config simplification (1.0), the `.env` uses `GCP_PROJECT_ID`, `GCP_AR_HOST`, and `GCP_AR_REPO`. This mismatch means `set -a && source .env && ./scripts/docker_build.sh --push` will fail to find the expected variables.

**Solution:** Update `docker_build.sh` to derive AR variables from the canonical `.env` names, or add a mapping layer. Alternatively, the build script should use the same `GCP_` prefixed variables that `GCPConfig` uses.

**Changes:** Not yet implemented — flagged for follow-up.

---

## 7.0 [P1] Pipeline Service Account Override for Vertex AI / Cloud Build

**Problem:** The default Vertex AI service account lacks Artifact Writer permissions required for Cloud Build. The derived pipeline SA (`{team}-{project}-{env}-pipeline@...`) may not have the correct permissions in sandbox environments. Teams need to use a specific pre-provisioned SA (e.g., `gc-sa-for-dta-gdpgenie@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com`) instead.

**Solution:** Added an optional `pipeline_service_account_email` field to `GCPConfig`. When set, it overrides the naming-convention-derived SA. When blank, the framework falls back to the existing derivation logic (`{team}-{project}-{env}-pipeline@{project}.iam.gserviceaccount.com`).

**Changes:**

- `gcp_ml_framework/config.py` (`GCPConfig`): Added `pipeline_service_account_email: str = ""` field. Read from env var `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL`.
- `gcp_ml_framework/context.py` (`MLContext`):
  - Added `pipeline_service_account_email: str = ""` field.
  - `from_config`: Passes `cfg.gcp.pipeline_service_account_email` through to MLContext.
  - `pipeline_service_account` property: Returns the explicit override when set, otherwise falls back to the derived convention.
- `.env`: Add `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL=gc-sa-for-dta-gdpgenie@prj-0n-dta-pt-ai-sandbox.iam.gserviceaccount.com`.

---

## 8.0 [P0] Inconsistency in run signature.

**Problem:** Return type of `run` method in `BaseComponent` is set to None. But in `Register` component, `run` returns a string.

---

## 9.0 [P2] Swapped `cast()` Arguments in Training Step

**Problem:** `pipelines/house_price/steps/train_regression_model.py` called `cast(client.query(query).to_dataframe(), pd.DataFrame)` with arguments in the wrong order. `typing.cast` is a no-op at runtime that returns its **second** argument, so this returned the class `pd.DataFrame` itself instead of the query result. This caused `TypeError: type 'DataFrame' is not subscriptable` when the Vertex AI pipeline tried to access `df["price"]`.

**Solution:** Swapped the arguments to `cast(pd.DataFrame, client.query(query).to_dataframe())`.

**Changes:**

- `pipelines/house_price/steps/train_regression_model.py`: Fixed `cast()` argument order.

---

## 10.0 [P3] Pylance/Type Check Fixes in BaseComponent

**Problem:** Two type-checking issues in the framework base classes:

1. `_task_type` ClassVar in `BaseComponent` was accessed externally by `decorators.py` and `pipeline/builder.py`, triggering Pylance `reportPrivateUsage` warnings since the underscore prefix marks it as private.
2. `BaseComponent` extends `BaseSettings` (pydantic-settings) but used `ConfigDict` (from pydantic) instead of `SettingsConfigDict`, causing a type mismatch error.

**Solution:** Renamed `_task_type` to `task_type` (public) and replaced `ConfigDict` with `SettingsConfigDict`.

**Changes:**

- `gcp_ml_framework/components/base.py`: Renamed `_task_type` → `task_type`. Changed `ConfigDict` → `SettingsConfigDict`. Removed unused `BaseModel` import.
- `gcp_ml_framework/decorators.py`: Updated both `@task` and `@ml_task` decorators to use `cls.task_type`. Fixed `ml_task` decorator type signature — used `@overload` to properly type both bare (`@ml_task`) and parameterized (`@ml_task(machine_type=...)`) usage patterns. Replaced lowercase `callable` with `Callable[[_C], _C]` for strict Pylance compliance. Used `TypeVar("_C", bound=type[BaseComponent])` to preserve the decorated class type through the decorator.
- `gcp_ml_framework/pipeline/builder.py`: Updated `getattr` lookup to use `"task_type"`.

**Remaining Pylance strict-mode items (not yet fixed):**

- Untyped `dict` return types in `pipeline/compiler.py` (`_build_context_params`, `_build_derived_params`) — should be `dict[str, str]` / `dict[str, dict[str, Any]]`.
- Missing return type on `cli/_helpers.py:load_pipeline()` and `secrets/client.py:make_secret_client()`.
- `-> Any` returns in `feature_store/client.py` and `pipeline/runner.py` (Google SDK types).
- Untyped `**kwargs` in `components/base.py:_run()`.

---

## 11.0 [P2] Circular Import Fix — Extract TaskType to `types.py`

**Problem:** `decorators.py` imported `BaseComponent` to type-annotate the decorator, and `BaseComponent` imported from `decorators.py` for `@task`/`@ml_task`. This caused a circular import at module load time.

**Solution:** Extracted `TaskType` enum into a new `gcp_ml_framework/types.py` module. Both `decorators.py` and `components/base.py` import `TaskType` from there. `decorators.py` uses a `TYPE_CHECKING` guard for its `BaseComponent` reference.

**Changes:**

- `gcp_ml_framework/types.py` (NEW): Created with `TaskType(StrEnum)` containing `TASK` and `ML_TASK`.
- `gcp_ml_framework/decorators.py`: Imports `TaskType` from `types.py`. Uses `TYPE_CHECKING` guard for `BaseComponent`.
- `gcp_ml_framework/components/base.py`: Imports `TaskType` from `types.py` instead of defining it locally.
- `gcp_ml_framework/pipeline/builder.py`: Imports `TaskType` from `types.py`.
- `gcp_ml_framework/pipeline/smart_compiler.py`: Imports `TaskType` from `types.py`.
- `gcp_ml_framework/__init__.py`: Re-exports `TaskType` from `types.py`.

---

## 12.0 [P2] Lazy Import for `google-cloud-aiplatform` in RegisterModel

**Problem:** `RegisterModel.run()` imports `google.cloud.aiplatform` at module level, causing `ImportError` when the package isn't installed locally (it's only available inside the pipeline Docker container).

**Solution:** Moved the import inside the `run()` method so it's only triggered at execution time.

**Changes:**

- `gcp_ml_framework/components/ml/register.py`: Moved `from google.cloud import aiplatform` from top-level to inside `run()`.

---

## 13.0 [P1] Multi-Image Docker Strategy with Consolidated Naming

**Problem:** The framework assumed one Docker image per pipeline. Real ML workflows
need separate containers for training (heavy deps) vs serving (lightweight HTTP runtime),
and different pipelines may need custom images. Additionally, image naming logic was
duplicated between the bash build script and the Python framework, risking drift.

**Design discussion:** See `docs/docker_discussion.md` for the full design document
covering problem statement, approaches considered, and rationale.

**Solution:** Implemented a co-located named Dockerfile approach with consolidated
naming resolution:

- **Directory structure**: Root-level defaults (`docker/train.Dockerfile`,
  `docker/serve.Dockerfile`) plus pipeline-specific overrides
  (`docker/pipelines/{name}/*.Dockerfile`).
- **Unrestricted naming**: Any `*.Dockerfile` is valid — no hardcoded "train"/"serve".
- **Component-level image binding**: `image_name` field on `BaseComponent` maps a
  Dockerfile stem to its image. The compiler resolves it to a full AR URI.
- **Three-tier resolution** for `RegisterModel.serving_container_image`:
  1. `serving_container_image` (full URI) — escape hatch
  2. `image_name` (Dockerfile stem) — resolved via `NamingConvention`
  3. Neither set — falls back to default training image
- **Race condition prevention**: Image names are prefixed with `{pipeline}--` for
  pipeline-scoped Dockerfiles, with project-level AR repos and branch-level tags.
- **Single source of truth**: `NamingConvention.docker_image_name()` in `naming.py`.
  The build script calls Python for name resolution, eliminating duplicate logic.

**Changes:**

- `gcp_ml_framework/naming.py`:
  - Added `docker_image_name(pipeline_name, dockerfile_stem)` static method — canonical
    image name derivation (root: `{stem}`, pipeline: `{pipeline}--{stem}`).
  - Added `docker_image_uri(...)` method — full AR URI for a Dockerfile, preserving
    the `--` delimiter.
- `gcp_ml_framework/components/base.py`:
  - Added `image_name: str = ""` field to `BaseComponent` — Dockerfile stem reference.
  - Added `image_name` to `_INTERNAL_FIELDS` (not exposed as KFP param).
- `gcp_ml_framework/pipeline/compiler.py`:
  - Added `_resolve_image_uri()` — resolves a Dockerfile stem to full AR URI via
    `NamingConvention.docker_image_uri()`.
  - `_build_kfp_pipeline`: Each step resolves its own image (from `component.image_name`
    or pipeline default). Replaces the single `base_image` approach.
  - `_build_derived_params`: RegisterModel serving image resolution now follows the
    three-tier priority (full URI > image_name stem > default).
- `scripts/docker_build.sh`:
  - Rewritten to support new directory structure (base → root defaults → pipeline-specific).
  - Delegates image name resolution to Python (`NamingConvention.docker_image_name()`).
  - Added **image registry** (`IMAGE_REGISTRY` associative array): maps stem → full tag
    as images are built. Dockerfiles reference base images by simple stem name
    (`ARG BASE_IMAGE=train`); the script auto-resolves to the full AR URI.
  - Added `--pipeline <name>` flag for selective builds.
- `scripts/resolve_image.py` (NEW): Thin CLI wrapper for `docker_image_name()` used
  by the build script.
- `docker/train.Dockerfile` (NEW): Default training image (moved from `docker/pipeline/Dockerfile`).
- `docker/serve.Dockerfile` (NEW): Default serving image with Vertex AI container
  requirements documented.
- `docker/pipelines/house_price/house_price_train.Dockerfile` (NEW): Example
  pipeline-specific training image inheriting from default.

