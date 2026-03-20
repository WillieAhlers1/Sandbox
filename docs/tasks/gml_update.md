# GCP ML Framework (`gcp_ml_framework/`) — Change Log

All changes made to the `gcp_ml_framework/` library compared to the original template (`~/Sandbox`).

---

## Migrate dataclasses to Pydantic BaseModel

**Problem:** All data classes in the framework used `@dataclass` from the standard library. Pydantic provides runtime validation, serialization, JSON Schema generation, and better integration with modern Python tooling. The config layer (`config.py`) already used Pydantic, creating inconsistency.

**Solution:** Converted all `@dataclass` classes to Pydantic `BaseModel` subclasses. Abstract base classes (`BaseComponent`, `BaseTask`) inherit from both `BaseModel` and `ABC`. Pattern mapping: `@dataclass` removed, `field(default_factory=...)` → `Field(default_factory=...)`, `__post_init__` → `model_post_init` or `@model_validator(mode="after")`.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/components/base.py` | 17-55: removed `from dataclasses import dataclass, field`, added `from pydantic import BaseModel, Field, ConfigDict`. `ComponentConfig` → `BaseModel`. `BaseComponent` → `BaseModel, ABC` with `model_config = ConfigDict(arbitrary_types_allowed=True)`. |
| `gcp_ml_framework/components/ingestion/bigquery_extract.py` | 2-6: removed `from dataclasses import dataclass, field`, added `from pydantic import Field`. Removed `@dataclass` decorator. |
| `gcp_ml_framework/components/ingestion/gcs_extract.py` | 2-6: same pattern — `dataclass` → `Field` import, `@dataclass` removed. |
| `gcp_ml_framework/components/feature_store/write_features.py` | 2-6: removed `dataclass` imports, added `from pydantic import Field`. Removed `@dataclass` from `WriteFeatures` and `ReadFeatures`. |
| `gcp_ml_framework/components/ml/train.py` | 2-10: removed `from dataclasses import dataclass, field`, added `from pydantic import Field`. Removed `@dataclass`. |
| `gcp_ml_framework/components/ml/train_container.py` | 9-19: removed `from dataclasses import dataclass, field` and `@dataclass` decorator. |
| `gcp_ml_framework/components/ml/deploy.py` | 2-6: removed `dataclass` imports, added `from pydantic import Field`. Removed `@dataclass`. |
| `gcp_ml_framework/components/ml/evaluate.py` | 2-6: same pattern. |
| `gcp_ml_framework/components/transformation/bq_transform.py` | 2-7, 38-43: removed `dataclass` imports, added `from pydantic import Field, model_validator`. `__post_init__` replaced with `@model_validator(mode="after")` named `_check_sql_source`. |
| `gcp_ml_framework/context.py` | 10, 16-48: `@dataclass(frozen=True)` → `BaseModel` + `ConfigDict(frozen=True, arbitrary_types_allowed=True)`. `raw_branch: str = field(compare=False)` → `Field(exclude=True)`. |
| `gcp_ml_framework/naming.py` | 14-81: `@dataclass(frozen=True)` → `BaseModel` + `ConfigDict(frozen=True, ignored_types=(cached_property,))`. `__post_init__` → custom `__init__` that slugifies fields before `super().__init__()`. |
| `gcp_ml_framework/feature_store/schema.py` | 21-68: `FeatureDef`, `FeatureGroupSchema`, `EntitySchema` all converted from `@dataclass` to `BaseModel`. |
| `gcp_ml_framework/dag/tasks/base.py` | 6, 13-34: `TaskConfig` and `BaseTask` → `BaseModel` / `BaseModel, ABC`. |
| `gcp_ml_framework/dag/tasks/bq_query.py` | 5, 23-38: removed `@dataclass`, `field(default=..., init=False)` → plain default value. |
| `gcp_ml_framework/dag/tasks/email.py` | 5, 14-28: same pattern. |
| `gcp_ml_framework/dag/tasks/vertex_pipeline.py` | 5, 15-43: `@dataclass` removed, added `ConfigDict`, `__post_init__` → `model_post_init`. |
| `gcp_ml_framework/dag/builder.py` | 19-47: `DAGTask` and `DAGDefinition` → `BaseModel` with `ConfigDict`. |
| `gcp_ml_framework/pipeline/builder.py` | 22-53: `PipelineStep` and `PipelineDefinition` → `BaseModel` with `Field`. |

---

## Fix Pydantic forward reference errors

**Problem:** After converting to Pydantic, several models failed at import time with `PydanticUserError: X is not fully defined`. Field types like `BaseComponent`, `BaseTask`, and `PipelineDefinition` were imported inside `if TYPE_CHECKING:` blocks. Pydantic needs field types resolvable at model-build time, unlike dataclasses.

**Solution:** Moved these imports from `TYPE_CHECKING` guards to regular runtime imports.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/pipeline/builder.py` | 21-23: moved `from gcp_ml_framework.components.base import BaseComponent` to runtime import. |
| `gcp_ml_framework/dag/builder.py` | 19-21: moved `from gcp_ml_framework.dag.tasks.base import BaseTask` to runtime import. |
| `gcp_ml_framework/dag/tasks/vertex_pipeline.py` | 7-12: moved `from gcp_ml_framework.pipeline.builder import PipelineDefinition` to runtime import. |

---

## Update compiler to use Pydantic model_fields

**Problem:** `pipeline/compiler.py` used `dataclasses.is_dataclass()` and `dataclasses.fields()` in `_step_params()` to extract component field values for KFP compilation. After the Pydantic migration, `is_dataclass()` returned `False` and no parameters were extracted, causing KFP compilation to fail with `TypeError: train-model() missing 5 required arguments`.

**Solution:** Replaced `dataclasses` introspection with `isinstance(component, BaseModel)` and `component.model_fields` iteration. Added `component_version` to the exclusion list.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/pipeline/compiler.py` | 199-220: `_step_params` method body rewritten — `dataclasses.is_dataclass` → `isinstance(component, BaseModel)`, `fields(component)` → `component.model_fields`. |

---

## Replace print() with loguru

**Problem:** All logging used bare `print()` with manual tag prefixes like `[local]`, `[dag-local]`, `[trainer]`. No timestamps, no log levels, no module context, and no filtering capability.

**Solution:** Replaced all `print()` calls with `logger.info()` from loguru. Dropped manual `[tag]` prefixes since loguru automatically includes timestamps, module name, function name, and line numbers. `console.print()` and `err_console.print()` (Rich CLI output) were intentionally left unchanged.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/pipeline/runner.py` | 14-15 (import), 82, 101, 104-109, 130, 133, 149, 151 (logger calls replacing print) |
| `gcp_ml_framework/dag/runner.py` | 18-19 (import), 67, 87, 89-90, 102-106, 129, 151-153, 159, 198, 284, 314-328 (logger calls) |
| `gcp_ml_framework/components/feature_store/write_features.py` | 5 (import), 79, 99, 114-118, 204, 206, 210 (logger calls) |
| `gcp_ml_framework/components/ml/evaluate.py` | 5 (import), 78, 93, 104, 124, 126, 146, 148 (logger calls) |
| `gcp_ml_framework/components/ml/train.py` | 8 (import), 146, 162-164, 212, 254 (logger calls) |
| `gcp_ml_framework/components/ml/deploy.py` | 5 (import), 108-109 (logger calls) |
| `gcp_ml_framework/components/ml/train_entrypoint.py` | 27 (import), 93 (logger call) |
| `gcp_ml_framework/feature_store/client.py` | 16-18 (import), 216 (logger call) |

---

## Make local runner invoke trainer script

**Problem:** `gml run <pipeline> --local` ran a generic inline sklearn model built into `TrainModel.local_run()`. It never executed the pipeline's actual `trainer/train.py` script. Local runs didn't test the real training code.

**Solution:** Thread `pipeline_dir` from the CLI through the runner to the component. When a `trainer/train.py` exists in the pipeline directory, invoke it as a subprocess with `--model-output`, `--project-id`, and all hyperparameters as CLI args. Priority order: trainer script → inline sklearn model → placeholder JSON.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/cli/cmd_run.py` | 147: added `pipeline_dir=pipeline_dir` to `LocalRunner()` constructor call. |
| `gcp_ml_framework/pipeline/runner.py` | 48-52: `LocalRunner.__init__` accepts new `pipeline_dir` param, stores as `self._pipeline_dir`. 139: passes `pipeline_dir` in kwargs to `local_run()`. |
| `gcp_ml_framework/components/ml/train.py` | 157-168: `local_run()` reads `pipeline_dir` from kwargs, calls `_run_trainer_script` before fallback training. 194-217: new `_run_trainer_script` method — discovers `trainer/train.py`, builds subprocess command with `--model-output`, `--project-id`, and hyperparameters, runs it. |

---

## Support {artifact_registry} template variable in trainer image URI

**Problem:** Trainer image URIs needed to reference the Artifact Registry path, which is dynamically computed from `artifact_registry_host` and `gcp_project`. There was no way to use a placeholder in `trainer_image` configuration.

**Solution:** `TrainModel.resolve_image_uri()` now checks if `trainer_image` contains `{artifact_registry}`. If so, it resolves the full AR repo path via `context.naming.artifact_registry_repo()` and substitutes the placeholder.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `gcp_ml_framework/components/ml/train.py` | 54-59: added `{artifact_registry}` template check and substitution in `resolve_image_uri()` before returning user-supplied `trainer_image`. |

---

## Derive IMAGE_TAG from git in docker_build.sh

**Problem:** `docker_build.sh` used `TAG="${IMAGE_TAG:-latest}"`, defaulting to `latest` when `IMAGE_TAG` was not set. Meanwhile, `naming.py:image_tag()` always derives the tag as `{branch}-{short_sha}` from git. When `.env` had a stale `IMAGE_TAG` (e.g. from an older commit), pushed images had a different tag than what the compiled KFP YAML referenced, causing Vertex AI to fail pulling images.

**Solution:** Replaced the static default with git-derived tag logic matching `naming.py`. When `IMAGE_TAG` is unset, the script now computes `{branch}-{short_sha}` from `git rev-parse`. Removed `IMAGE_TAG` from `.env` so both the build script and Python naming module produce identical tags.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `scripts/docker_build.sh` | 30-38: replaced `TAG="${IMAGE_TAG:-latest}"` with git-derived `TAG="${_branch}-${_sha}"` fallback, matching `naming.py`. |
| `.env` | 4: removed stale `IMAGE_TAG=test-11322fa`, added comment explaining it is intentionally not set. |

---

## Fix docker buildx build context and push for docker-container driver

**Problem:** Two issues with `docker buildx build --platform linux/amd64`: (1) `_build_base_ml` used `docker/base/base-ml` as build context, but its Dockerfile COPYs `pyproject.toml`, `second_run/`, and `pipelines/` which exist at the repo root — causing `failed to compute cache key: "/pipelines": not found`. (2) The original `_push_all()` used `docker push` after building, but the `docker-container` buildx driver doesn't load images into the local Docker daemon, so `docker push` couldn't find them.

**Solution:** Changed `_build_base_ml` context from `docker/base/base-ml` to `.` (repo root). Replaced the separate `_push_all()` loop with `--push`/`--load` flags passed directly to `docker buildx build` — `--push` builds and pushes atomically when pushing, `--load` loads images into the local daemon for non-push builds (needed so base-python is available as a base for subsequent layers).

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `scripts/docker_build.sh` | 72-86: `_build()` now passes `--push` or `--load` to buildx directly instead of relying on a separate push step. Removed `_push_all()` function. 107: `_build_base_ml` context changed from `docker/base/base-ml` to `.`. |

---

## Restore trainer requirements.txt

**Problem:** `pipelines/training_pipeline/trainer/requirements.txt` was missing. `docker_build.sh:_build_trainers()` requires both `trainer/train.py` AND `trainer/requirements.txt` to detect a pipeline as having a trainer image. Without `requirements.txt`, the build script skipped the trainer entirely, outputting `No pipelines with trainer/ directories found.` The generated Dockerfile also COPYs `requirements.txt`, so the build would fail even if detection were bypassed.

**Solution:** Created an empty `requirements.txt` with a comment explaining that all trainer deps are already provided by `base-ml` (via `pyproject.toml`'s `trainer` extra: scikit-learn, numpy, typer, loguru, google-cloud-bigquery, pandas). No additional packages needed.

**Files Modified:**

| File | Lines Modified |
|------|---------------|
| `pipelines/training_pipeline/trainer/requirements.txt` | 1-3: new file (comment-only, no packages). |

---

## Convert all components from `@dsl.component` to `@dsl.container_component`

**Problem:** All components used `@dsl.component` which embeds the Python function body directly in compiled KFP YAML. This caused code duplication (in the image AND in the YAML), runtime `packages_to_install` adding latency (pip install on every run), and no control over the execution environment beyond the base image.

**Solution:** Converted all components to `@dsl.container_component` returning `dsl.ContainerSpec` with `image`, `command`, and `args`. Each component file now has a `__main__` block with `argparse` that invokes the same logic as the old embedded function body. The component-base image has all framework code installed, so each component is invoked via `python -m gcp_ml_framework.components.<module>`. Added `scikit-learn>=1.4` to the `components` extra in `pyproject.toml` since there's no more runtime pip install. Simplified `compiler.py` output wiring to always use `task.outputs["output_uri"]`.

**Files Modified:**

| File | Changes |
|------|---------|
| `pyproject.toml` | Added `scikit-learn>=1.4` to `components` optional-dependencies. |
| `gcp_ml_framework/components/base.py` | Updated docstrings: `@dsl.component` → `@dsl.container_component`. |
| `gcp_ml_framework/components/ingestion/bigquery_extract.py` | `@dsl.component` → `@dsl.container_component` returning `ContainerSpec`. Added `__main__` block with argparse + BQ query/export logic. |
| `gcp_ml_framework/components/ingestion/gcs_extract.py` | Same pattern — container_component + `__main__` block with GCS copy logic. |
| `gcp_ml_framework/components/transformation/bq_transform.py` | Same pattern — container_component + `__main__` block with BQ transform logic. |
| `gcp_ml_framework/components/feature_store/write_features.py` | Converted both `WriteFeatures` and `ReadFeatures`. `__main__` dispatches on `--mode write` vs `--mode read`. |
| `gcp_ml_framework/components/ml/train.py` | Container_component + `__main__` block with CustomJob submission logic. |
| `gcp_ml_framework/components/ml/evaluate.py` | Container_component + `__main__` block with evaluation logic. Removed `packages_to_install=["scikit-learn>=1.4"]`. |
| `gcp_ml_framework/components/ml/deploy.py` | Container_component + `__main__` block with deploy logic. |
| `gcp_ml_framework/pipeline/compiler.py` | Removed `@dsl.component` branch (`task.output`); all components now use `task.outputs["output_uri"]`. |
