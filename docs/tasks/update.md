## Upgrade base-python to Python 3.12 with uv
#### Problem
The base Docker image used Python 3.11 and plain `pip`. The rest of the project uses Python 3.12 and `uv` for dependency management, causing version mismatches and inconsistent builds across the image hierarchy.

#### Solution
Upgraded to `python:3.12-slim` and installed `uv` in the base layer. Added environment variables (`UV_NO_CACHE`, `UV_NO_ENV_FILE`, `UV_PROJECT_ENVIRONMENT`) so all child images inherit a consistent `uv` configuration.

| File | Lines modified |
|------|---------------|
| `docker/base/base-python/Dockerfile` | 1-10 (entire file rewritten) |

---

## Replace flat pip install with uv sync in base-ml
#### Problem
`base-ml` used a flat `pip install` of ML packages (`numpy pandas scikit-learn xgboost lightgbm pyarrow`). This duplicated dependency specifications already in `pyproject.toml` and didn't benefit from Docker layer caching — any change rebuilt everything. Additionally, `python3-dev` was initially included but caused a build failure because the Debian package pulled in `python3-minimal` which tried to configure Python 3.13, conflicting with the base image's Python 3.12.

#### Solution
Switched to `uv sync --extra trainer` which reads from `pyproject.toml` (single source of truth). Split into two Docker layers: (1) dependencies only (cached until `pyproject.toml` changes) and (2) source code (changes often but doesn't bust the dep cache). Removed `python3-dev` since `python:3.12-slim` already includes Python headers for C extension compilation.

| File | Lines modified |
|------|---------------|
| `docker/base/base-ml/Dockerfile` | 1-34 (entire file rewritten) |

---

## Replace flat pip install with uv sync in component-base
#### Problem
Same as base-ml — `component-base` used a flat `pip install` of GCP SDK and KFP packages, then redundantly installed `uv` again and ran `uv sync --all-groups`. Dependencies were specified in two places (Dockerfile and `pyproject.toml`). Also had the same `python3-dev` conflict.

#### Solution
Same two-layer Docker caching pattern with `uv sync --extra components`. Removed redundant `uv`/`pip` installs (now handled by base-python). Removed `python3-dev` to fix the Python 3.13 conflict.

| File | Lines modified |
|------|---------------|
| `docker/base/component-base/Dockerfile` | 1-35 (entire file rewritten) |

---

## Add .dockerignore
#### Problem
Docker build contexts included everything in the repo — `.git`, `.venv`, `terraform/`, `.env`, compiled artifacts, etc. This slowed builds and risked leaking secrets or state into images.

#### Solution
Added `.dockerignore` to exclude non-essential files. `README.md` is explicitly included (needed by `pyproject.toml` metadata) while all other `.md` files are excluded.

| File | Lines modified |
|------|---------------|
| `.dockerignore` | 1-23 (new file) |

---

## Fix docker_build.sh for Apple Silicon and buildx push
#### Problem
Three issues with the original build script: (1) `docker build` produced `linux/arm64` images on Apple Silicon Macs, which fail on Vertex AI (requires `linux/amd64`). (2) `_build_base_ml` used `docker/base/base-ml` as build context, but the Dockerfile COPYs `pyproject.toml`, `second_run/`, and `pipelines/` from repo root — causing `"/pipelines": not found`. (3) The separate `_push_all()` with `docker push` doesn't work with `docker-container` buildx driver (images aren't loaded locally). (4) `TAG` defaulted to `latest` instead of matching `naming.py`'s `{branch}-{short_sha}` convention.

#### Solution
Changed `docker build` to `docker buildx build --platform linux/amd64`. Replaced `_push_all()` with `--push`/`--load` flags passed directly to `docker buildx build` — `--push` builds and pushes atomically, `--load` makes images available locally for non-push builds. Changed `_build_base_ml` context from `docker/base/base-ml` to `.` (repo root). Replaced `TAG="${IMAGE_TAG:-latest}"` with git-derived `{branch}-{short_sha}` tag matching `naming.py`. Removed stale `IMAGE_TAG` from `.env`.

| File | Lines modified |
|------|---------------|
| `scripts/docker_build.sh` | 30-38 (git-derived tag), 64-86 (`_build()` uses buildx with `--platform linux/amd64` and `--push`/`--load`; removed `_push_all()`), 107 (`_build_base_ml` context changed to `.`) |
| `.env` | 4 (removed stale `IMAGE_TAG=test-11322fa`) |

---

## Convert trainer CLI to Typer Options
#### Problem
The trainer script used positional Typer arguments. When invoked by Vertex AI CustomJob or by the local runner, arguments must be passed as `--flag value` (not positional), causing invocation failures.

#### Solution
Changed to explicit `Option(...)` declarations so args are passed as `--model-output` and `--project-id`. Added loguru logging statements for training visibility.

| File | Lines modified |
|------|---------------|
| `pipelines/training_pipeline/trainer/train.py` | 11 (`from typer import Typer, Option`), 23-24 (Option declarations), 27, 30, 39, 44 (logger.info calls) |

---

## Normalize project_name underscores in Terraform
#### Problem
`project_name` is `second_run` (with underscores), but GCP resource IDs (bucket names, AR repos) don't allow underscores. Terraform was creating resources with invalid names like `mlplatform-second_run`.

#### Solution
Added `local.project_slug` that replaces underscores with hyphens, and used it in resource name construction for storage and artifact registry modules.

| File | Lines modified |
|------|---------------|
| `terraform/envs/dev/main.tf` | 58-60 (`locals` block), 73 (bucket_name), 85 (repository_id) |
| `terraform/envs/staging/main.tf` | Same pattern |
| `terraform/envs/prod/main.tf` | Same pattern |

---

## Add IAM bindings for Composer to Vertex AI
#### Problem
The Composer (Airflow) service account couldn't submit Vertex AI pipeline jobs. DAG runs failed with permission errors because the SA lacked `aiplatform.user` role and couldn't impersonate the Pipeline SA.

#### Solution
Added two IAM bindings: (1) `roles/aiplatform.user` for the Composer SA to submit pipeline jobs, and (2) `roles/iam.serviceAccountUser` so Composer SA can act as the Pipeline SA when submitting Vertex jobs.

| File | Lines modified |
|------|---------------|
| `terraform/envs/dev/main.tf` | 94-110 (two new IAM resource blocks) |

---

## Move loguru and typer to core dependencies
#### Problem
`loguru` was only in the `trainer` extra and `typer` was only in `components` and `trainer` extras. After replacing all `print()` calls with `loguru.logger` across the framework, loguru needed to be available everywhere — not just in trainer images.

#### Solution
Moved `loguru>=0.7.3` from `[project.optional-dependencies] trainer` to `[project] dependencies`. Added `typer>=0.15` to core dependencies. Removed duplicate `loguru` from trainer extra.

| File | Lines modified |
|------|---------------|
| `pyproject.toml` | 10 (added loguru to core deps), 12 (added typer to core deps), 27 (removed loguru from trainer extra) |

---

## Replace print() with loguru
#### Problem
All logging in `gcp_ml_framework/` used bare `print()` with manual tag prefixes like `print(f"[pipeline-local] ...")`. This provided no timestamps, no log levels, no module context, and couldn't be filtered or redirected.

#### Solution
Replaced all bare `print()` calls with `logger.info()` from loguru. Dropped manual `[tag]` prefixes since loguru automatically includes timestamps, module name, function name, and line numbers. `console.print()` and `err_console.print()` (Rich formatted CLI output) were intentionally left unchanged.

| File | Lines modified |
|------|---------------|
| `gcp_ml_framework/pipeline/runner.py` | 14 (import), 80, 99, 102-107, 128, 131, 147, 149 (logger calls) |
| `gcp_ml_framework/dag/runner.py` | 18 (import), 66, 86, 89, 102, 129, 151-153, 159, 198, 284, 314, 316, 318, 325, 327-328 (logger calls) |
| `gcp_ml_framework/components/feature_store/write_features.py` | 5 (import), 79, 99, 114-115, 117-118, 204, 206, 210 (logger calls) |
| `gcp_ml_framework/components/ml/evaluate.py` | 5 (import), 78, 93, 104, 124, 126, 146, 148 (logger calls) |
| `gcp_ml_framework/components/ml/train.py` | 7 (import), 145, 161-163, 210, 213, 252 (logger calls) |
| `gcp_ml_framework/components/ml/deploy.py` | 5 (import), 108-109 (logger calls) |
| `gcp_ml_framework/components/ml/train_entrypoint.py` | 27 (import), 93 (logger call) |
| `gcp_ml_framework/feature_store/client.py` | 16 (import), 215 (logger call) |

---

## Migrate dataclasses to Pydantic BaseModel
#### Problem
All data classes in the framework used `@dataclass` from the standard library, while the config layer (`config.py`) already used Pydantic. This created inconsistency: some classes validated input, others didn't. Pydantic also provides serialization, schema generation, and runtime type checking that dataclasses lack.

#### Solution
Converted all 26 dataclasses across 18 files to Pydantic `BaseModel`. The key architectural decision was making the abstract base classes (`BaseComponent`, `BaseTask`) inherit from both `BaseModel` and `ABC`, so subclasses only need single inheritance. Pattern mapping: `@dataclass` removed → class inherits `BaseModel`; `field(default_factory=...)` → `Field(default_factory=...)`; `__post_init__` → `model_post_init` or `@model_validator(mode="after")`.

| File | Lines modified |
|------|---------------|
| `gcp_ml_framework/components/base.py` | 20 (pydantic import), 26 (`ComponentConfig(BaseModel)`), 37 (`BaseComponent(BaseModel, ABC)`), 47 (model_config), 52 (Field) |
| `gcp_ml_framework/components/ingestion/bigquery_extract.py` | 5 (pydantic import), 13 (class inherits BaseComponent), 33 (Field) |
| `gcp_ml_framework/components/ingestion/gcs_extract.py` | 5 (pydantic import), 13 (class inherits BaseComponent), 27 (Field) |
| `gcp_ml_framework/components/feature_store/write_features.py` | 6 (pydantic import), 14 (`WriteFeatures(BaseComponent)`), 34, 37 (Fields), 122 (`ReadFeatures(BaseComponent)`), 132, 135 (Fields) |
| `gcp_ml_framework/components/ml/train.py` | 8 (pydantic import), 17 (`TrainModel(BaseComponent)`), 39-42 (Fields) |
| `gcp_ml_framework/components/ml/train_container.py` | 20 (`TrainModel(_OriginalTrainModel)`, removed @dataclass) |
| `gcp_ml_framework/components/ml/deploy.py` | 6 (pydantic import), 14 (`DeployModel(BaseComponent)`), 37, 39 (Fields) |
| `gcp_ml_framework/components/ml/evaluate.py` | 6 (pydantic import), 14 (`EvaluateModel(BaseComponent)`), 28-29, 31 (Fields) |
| `gcp_ml_framework/components/transformation/bq_transform.py` | 6 (pydantic import), 14 (`BQTransform(BaseComponent)`), 38 (Field), 40-44 (`@model_validator` replacing `__post_init__`) |
| `gcp_ml_framework/dag/tasks/base.py` | 6 (pydantic import), 13 (`TaskConfig(BaseModel)`), 24 (`BaseTask(BaseModel, ABC)`), 33 (Field) |
| `gcp_ml_framework/dag/tasks/bq_query.py` | 5 (pydantic import), 24 (`BQQueryTask(BaseTask)`), 39 (Field) |
| `gcp_ml_framework/dag/tasks/email.py` | 5 (pydantic import), 15 (`EmailTask(BaseTask)`), 27-28, 31 (Fields) |
| `gcp_ml_framework/dag/tasks/vertex_pipeline.py` | 5 (pydantic import), 15 (`VertexPipelineTask(BaseTask)`), 29 (model_config), 32, 38 (Fields), 40-43 (model_post_init) |
| `gcp_ml_framework/dag/builder.py` | 19 (pydantic import), 24 (`DAGTask(BaseModel)`), 27 (model_config), 31, 45, 47 (Fields), 34 (`DAGDefinition(BaseModel)`) |
| `gcp_ml_framework/pipeline/builder.py` | 22 (pydantic import), 27 (`PipelineStep(BaseModel)`), 30 (model_config), 37 (`PipelineDefinition(BaseModel)`), 47 (model_config), 51, 53 (Fields) |
| `gcp_ml_framework/context.py` | 10 (pydantic import), 16 (`MLContext(BaseModel)`), 31 (model_config frozen=True), 45 (Field) |
| `gcp_ml_framework/naming.py` | 17 (pydantic import), 57 (`NamingConvention(BaseModel)`), 71 (model_config frozen=True, ignored_types) |
| `gcp_ml_framework/feature_store/schema.py` | 26 (pydantic import), 41 (`FeatureDef(BaseModel)`), 47 (`FeatureGroupSchema(BaseModel)`), 50, 53, 65 (Fields) |

---

## Fix Pydantic forward reference errors
#### Problem
After converting to Pydantic, several models failed at import time with `PydanticUserError: X is not fully defined`. Field types like `BaseComponent`, `BaseTask`, and `PipelineDefinition` were imported inside `if TYPE_CHECKING:` blocks. With dataclasses this was fine (they don't validate types at class creation), but Pydantic needs field types resolvable at model-build time.

#### Solution
Moved these imports from `TYPE_CHECKING` guards to regular runtime imports.

| File | Lines modified |
|------|---------------|
| `gcp_ml_framework/pipeline/builder.py` | 24 (moved `from gcp_ml_framework.components.base import BaseComponent` to runtime) |
| `gcp_ml_framework/dag/builder.py` | 21 (moved `from gcp_ml_framework.dag.tasks.base import BaseTask` to runtime) |
| `gcp_ml_framework/dag/tasks/vertex_pipeline.py` | 8 (moved `from gcp_ml_framework.pipeline.builder import PipelineDefinition` to runtime) |

---

## Update compiler to use Pydantic model_fields
#### Problem
`pipeline/compiler.py` used `dataclasses.is_dataclass()` and `dataclasses.fields()` in `_step_params()` to extract component field values for KFP compilation. After the Pydantic migration, components are no longer dataclasses, so `is_dataclass()` returned `False` and no parameters were extracted. This caused KFP compilation to fail with `TypeError: train-model() missing 5 required arguments`.

#### Solution
Replaced `dataclasses` introspection with Pydantic's `isinstance(component, BaseModel)` check and `component.model_fields` iteration.

| File | Lines modified |
|------|---------------|
| `gcp_ml_framework/pipeline/compiler.py` | 198-218 (replaced `_step_params` method body: `dataclasses.is_dataclass` → `isinstance(component, BaseModel)`, `fields(component)` → `component.model_fields`) |

---

## Make local runner invoke trainer script
#### Problem
`gml run <pipeline> --local` ran a generic inline sklearn model built into `TrainModel.local_run()`. It never executed the pipeline's actual trainer at `pipelines/<name>/trainer/train.py`. Local runs didn't test the real training code — they tested a hardcoded stub.

#### Solution
Three-part change to thread `pipeline_dir` from the CLI through the runner to the component, then discover and subprocess the trainer script. The subprocess inherits stdout/stderr so loguru output from the trainer streams to the terminal. The full command is logged before execution. Priority order: trainer script → inline sklearn model → placeholder JSON.

| File | Lines modified |
|------|---------------|
| `gcp_ml_framework/cli/cmd_run.py` | 147 (added `pipeline_dir=pipeline_dir` to LocalRunner constructor) |
| `gcp_ml_framework/pipeline/runner.py` | 47-49 (`__init__` accepts `pipeline_dir` param), 137 (passes `pipeline_dir` in kwargs to `local_run`) |
| `gcp_ml_framework/components/ml/train.py` | 167-168 (reads `pipeline_dir` from kwargs), 170-171 (calls `_run_trainer_script` before inline training), 192-215 (new `_run_trainer_script` method: discovers `trainer/train.py`, builds CLI command, logs it, runs subprocess) |
