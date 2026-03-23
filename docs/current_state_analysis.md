# Current State Analysis — GAP / GCP ML Framework

**Date:** 2026-03-23
**Branch:** `version_1_enc` (based on `version_1` @ `6dc3986`)
**Scope:** Dev environment only. CI/CD is out of scope.
**Test baseline:** 61 failed, 105 passed, 60 errors (226 selected of 228 collected), 19 ruff errors
**REQS completion:** 11 done, 7 partial, 4 not done, 1 deferred

---

## 1. Executive Summary

The project is a **GCP ML Pipeline Framework** (`gcp_ml_framework`) that enables data scientists to define ML pipelines in Python using a fluent builder API, auto-compiling them into Airflow DAGs for Cloud Composer orchestration and KFP v2 YAML for Vertex AI pipeline execution. The framework is post-PR #26 with core architecture sound: unified component lifecycle (`cli()`/`execute()`/`run()`), Pydantic BaseSettings for components, SmartCompiler for mixed task grouping, and NamingConvention as single source of truth for all GCP resource names. Of 23 REQS items, 11 are fully done, 7 are partially implemented, 4 are not started, and 1 (CI/CD separation) is deferred. The most critical gaps are 7 runtime bugs (including a NameError in `compiler.py`, dead code in `train.py`, and AttributeError in `bq_query.py`), 60 test errors from a stale conftest fixture, and legacy Dockerfiles that contradict the client's PR #26 design. The prioritized action plan in `docs/tasks/todo.md` addresses all issues across 8 phases, from critical runtime fixes through new capabilities.

---

## 2. Client PR Analysis

### Commit History (version_1 branch)

```
f7987e1 Merge pull request #26 from ragrawal/v1_rj
c24ed0a updated docs
82f4d47 fixed registery component
d4fb537 Merge pull request #25 from ragrawal/v1_rj
8f06131 Merge PR for fixed registery component (#24)
d9d18ef Merge PR #23: client Docker naming convention and image resolution fixes
54508b7 Phases 5 + 5.5
0682502 Phase 4.5
ef917fd Phases 1-4
8ff33ee Initial commit: second_run-test codebase as version_1
```

### PR #23 — Docker Naming Convention (`d9d18ef`, 20 files, +1048/-208)

**Purpose:** Establish `NamingConvention.docker_image_name()` as single source of truth for Docker image naming, simplify GCP config from multi-env project IDs to a single `project_id`.

**Key changes:**
- **GCPConfig simplified:** Removed `dev_project_id`, `staging_project_id`, `prod_project_id`. Replaced with single `project_id: str` field. Rationale: separate GCP projects per environment means one project ID suffices.
- **`FrameworkConfig.active_gcp_project`:** Now simply returns `self.gcp.project_id` instead of environment-switch logic.
- **`.env.example` created:** Standardized config with `GCP_PROJECT_ID`, `GCP_REGION`, etc. (no `GML_` prefix for framework vars).
- **`NamingConvention.docker_image_name()`:** Static method deriving image names from `(pipeline_name, dockerfile_stem)`. Pipeline-scoped images use `{pipeline}--{stem}` delimiter.
- **`NamingConvention.docker_image_uri()`:** Composes full AR URI from dockerfile metadata + branch-SHA tag.
- **`decorators.py` TaskType extraction:** `@task` and `@ml_task` now set `cls.task_type` as a class variable (was `cls._task_type`). Tests still reference `._task_type`.
- **`BaseComponent` field rename:** `image_name` became `runtime_dockerfile` (path to Dockerfile relative to `docker/`).
- **`scripts/docker_build.sh` rewrite:** Now uses `_parse_dockerfile_path()` logic mirrored from Python.

**Why it matters:** This PR established the naming convention contract that Docker builds, the compiler, and the deployment pipeline all share. Before this, image names were ad-hoc strings.

### PR #24 — Registry Component (`8f06131`, 18 files, +531/-99)

**Purpose:** Implement model versioning via `parent_model` in Vertex AI Model Registry, create per-pipeline Docker image structure, add `serving_dockerfile` field.

**Key changes:**
- **New Dockerfile structure:** Created `docker/train.Dockerfile`, `docker/serve.Dockerfile` (root defaults), `docker/pipelines/house_price/train.Dockerfile` (pipeline-specific).
- **`docker_build_base.sh` created:** Separate script for building `base-python` image.
- **`RegisterModel` rewrite:** Added `serving_dockerfile` field for three-tier serving image resolution: (1) `serving_container_image` full URI, (2) `serving_dockerfile` path resolved by compiler, (3) fallback to default training image.
- **Smart model versioning:** `RegisterModel.run()` looks up existing models by `display_name`. If found, creates a new version under that `parent_model`. If not, creates v1.
- **`house_price` pipeline created:** Reference pipeline with `HouseTrainModelStep` + `RegisterModel` + `DeployModel`. Located at `pipelines/house_price/`.
- **`second_run/estimator.py`:** Contains `HousePredictionModel` — the data science team's model code, separate from framework code.

**Why it matters:** This PR established the pattern for how models get registered and how serving containers are resolved — a critical path for production deployments.

### PR #25 — Deployment Component (`d4fb537`, 12 files, +518/-104)

**Purpose:** Restructure DeployModel to use model lookup (not model upload), add per-pipeline FastAPI serving apps, complete the Docker image hierarchy.

**Key changes:**
- **DeployModel rewrite:** Removed `endpoint_name` (was required), `model_uri`, `serving_container_image`. Added `model_name` — endpoint auto-derived via `vertex_endpoint_name(pipeline_name, model_name)`.
- **`run_deploy()` rewrite:** No longer takes `model_uri` or `serving_container_image`. Looks up registered model by `display_name`. Raises `ValueError` if not found.
- **`vertex_endpoint_name()` signature:** Changed from `(model_name)` to `(pipeline_name, model_name)` for namespace uniqueness.
- **New `app/house_price/app.py`:** FastAPI serving app implementing Vertex AI custom container protocol (`AIP_HTTP_PORT`, `AIP_HEALTH_ROUTE`, `AIP_PREDICT_ROUTE`).
- **New `docker/pipelines/house_price/base.Dockerfile`:** Pipeline-specific execution image.
- **New `docker/pipelines/house_price/serve.Dockerfile`:** Pipeline-specific serving image with FastAPI + uvicorn.
- **Compiler `_build_derived_params()` updated:** Adds `model_display_name` and `endpoint_display_name` for DeployModel. But left a dead block at lines 304-307 referencing undefined `serving_image`.

**Why it matters:** This PR completed the Register-to-Deploy lifecycle. DeployModel now depends on RegisterModel running first (model lookup pattern). But it broke 61 tests and introduced a runtime bug.

### PR #26 — Design Codification & Registry Fix (`f7987e1`, 3 files, +183/-159)

**Purpose:** Codify the client's architectural design decisions into authoritative documentation and fix the RegisterModel sync behavior.

**Key changes:**

- **`register.py` — Removed `sync=False`:** The `Model.upload()` call no longer passes `sync=False`. The model upload is now **synchronous** (waits for completion). However, `docs/register.md` still documents `sync=False` as the design decision — **this is a doc-code discrepancy** that must be resolved. The docs explain the rationale: `sync=True` polls the LRO via `GetOperation` calls, consuming the 600 req/min CRUD quota on shared projects and causing 429 errors. The code should align with the docs (re-add `sync=False`).

- **`docs/register.md` — Complete rewrite establishing design law:**
  1. **RegisterModel = SINGLE OWNER of serving container image.** `DeployModel` does NOT need or accept serving image fields. One source of truth, no duplication.
  2. **`model_name` = CONTRACT** between `RegisterModel` and `DeployModel`. Same identifier links registration to deployment via the naming convention.
  3. **Three-tier serving image priority:** (1) `serving_container_image` full URI, (2) `serving_dockerfile` resolved by compiler, (3) fallback to default training image.
  4. **Model versioning via `parent_model`:** Look up by `display_name`, create new version if exists, create v1 if not. Stateless — no cross-run state needed.
  5. **Branch isolation baked in:** Display names include branch slug, so models on different branches are separate parents.

- **`docs/deploy.md` — Complete rewrite establishing deployment law:**
  1. **Registration vs Deployment separation:** `RegisterModel` owns images + artifacts. `DeployModel` is pure deployment — find model, find endpoint, deploy. No serving image fields on DeployModel.
  2. **Why separate steps?** Early iterations had DeployModel re-uploading the model. This was redundant and created maintenance burden (change image in one place, forget the other).
  3. **Root-level default Dockerfiles REMOVED:** Client explicitly states: "Root-level default Dockerfiles (`docker/train.Dockerfile`, `docker/serve.Dockerfile`) were removed. Every pipeline explicitly declares its Dockerfiles." Only two per pipeline: `base.Dockerfile` + `serve.Dockerfile`.
  4. **`app/` separate from `pipelines/`:** Serving code lives at `app/{pipeline}/app.py`, NOT inside `pipelines/`. Different lifecycles (short-lived KFP steps vs long-lived web services).
  5. **Docker hierarchy simplified to two per pipeline:** `base.Dockerfile` (extends `base-python`, used for training/registration) + `serve.Dockerfile` (extends base, adds FastAPI + uvicorn, used for serving).

**Why it matters:** PR #26 is the client's design codification. These docs are **authoritative design decisions**, not just descriptions. Every choice has a rationale. We MUST follow them:
- No serving image fields on DeployModel — ever
- model_name is the contract — always
- Two Dockerfiles per pipeline (base + serve) — no root-level defaults
- RegisterModel owns serving image — single source of truth

**CRITICAL GAP: The codebase still has root-level Dockerfiles (`docker/train.Dockerfile`, `docker/serve.Dockerfile`, `docker/pipeline/Dockerfile`, `docker/serving/Dockerfile`) that the client's docs say should be removed. Also `docker/pipelines/house_price/train.Dockerfile` exists but the client's target is only `base.Dockerfile` + `serve.Dockerfile` per pipeline.**

---

## 3. REQS Status Matrix

Source: `docs/REQS.md` (22 requirements + 1 sub-requirement)

| REQ | Priority | Description | Status | Evidence |
|-----|----------|-------------|--------|----------|
| 1.0 | P0 | Unified Component Lifecycle | **DONE** | `container_component`, `cli()`, `execute()`, `run()` all exist in `base.py` |
| 2.0 | P1 | Underscore Normalization | **DONE** | `naming.py` `_slugify()` + terraform `locals { project_slug = replace(...) }` |
| 3.0 | P1 | Clean Invalid DAGs | **PARTIAL** | 3 stale DAGs exist from old compilation runs |
| 4.0 | P1 | Docker Build Tag | **DONE** | `docker_build.sh` always uses `{branch}-{sha}`, never `:latest` |
| 5.0 | P0 | Airflow 403 Permission | **DONE** | IAM bindings in `terraform/envs/dev/main.tf` |
| 6.0 | P0 | Compiled YAML | **DONE** | Resolved by 1.0, `container_component` used |
| 7.0 | P0 | Pydantic Migration | **PARTIAL** | `smart_compiler.py` still has 2 `@dataclass` (`CompilationResult`, `_StepGroup`) |
| 8.0 | P0 | Argparse to Typer | **DONE** | Zero argparse, `BaseComponent.cli()` uses Typer |
| 9.0 | P1 | Loguru Logging | **PARTIAL** | 12 files use loguru. CLI uses Rich `console.print()` (intentional for UI). Some framework code still has `print()` |
| 10.0 | P2 | Google-Style Docstrings | **PARTIAL** | Docstrings present but style varies, not enforced |
| 11.0 | P0 | Simplify PipelineBuilder | **DONE** | Single `.add()` method only |
| 12.0 | P0 | CLI Entrypoints | **DONE** | Resolved by 1.0 |
| 13.0 | P0 | Flatten ComponentConfig | **DONE** | Fields directly on `BaseComponent` |
| 14.0 | P0 | Expose Standard Variables | **DONE** | `project`, `region`, `branch`, `environment`, `run_date`, `dataset` on `BaseComponent` |
| 15.0 | P0 | GitState to Environment | **DONE** | `Environment` StrEnum in `config.py`, no GitState exists |
| 16.0 | P1 | CI/CD Separation | **DEFERRED** | Out of scope |
| 17.0 | P2 | Mypy | **PARTIAL** | 20 errors across 7 files (attr-defined, type mismatches, missing stubs) |
| 18.0a | P1 | Cloud Build Migration | **PARTIAL** | `cloudbuild.yaml` exists but references legacy Dockerfiles (`docker/pipeline/Dockerfile`, `docker/serving/Dockerfile`) |
| 18.0b | -- | Docker Hierarchy | **PARTIAL** | Client target (PR #26): `base-python` + 2 per pipeline. Root-level and legacy Dockerfiles still exist |
| 19.0 | P2 | DBT Integration | **NOT DONE** | Zero DBT code |
| 20.0 | P2 | AGENTS.md | **NOT DONE** | File missing |
| 21.0 | P0 | Model Registry | **DONE** | `RegisterModel` with `parent_model` versioning |
| 22.0 | P0 | Loop/Condition Operators | **NOT DONE** | No `dsl.ParallelFor`/`dsl.Condition` support |

**Summary:** 11 DONE, 7 PARTIAL, 4 NOT DONE, 1 DEFERRED.

---

## 4. Complete Bug Inventory

### 4.1 Critical Runtime Bugs

#### Bug 1: `serving_image` Undefined Variable — `compiler.py:305-307`

**File:** `gcp_ml_framework/pipeline/compiler.py`
**Lines:** 305-307
**Severity:** CRITICAL (NameError at compile time for any pipeline with RegisterModel or DeployModel)

```python
# RegisterModel/DeployModel: default serving container if not set
if isinstance(comp, (RegisterModel, DeployModel)):
    if not comp.serving_container_image:
        extra["serving_container_image"] = serving_image  # NameError
```

**Root cause:** Leftover from before PR #25. RegisterModel serving image resolution already happens at lines 280-290 (three-tier priority). DeployModel no longer needs a serving image (captured during registration). The variable `serving_image` was never defined in this scope.

**Fix:** Delete lines 305-307 entirely.

#### Bug 2: Dead Code After `raise NotImplementedError` — `train.py:77-104`

**File:** `gcp_ml_framework/components/ml/train.py`
**Lines:** 71, 77-104
**Severity:** CRITICAL (experiment tracking unreachable)

The `run()` method raises `NotImplementedError` at line 71. Lines 77-104 contain experiment tracking code that is unreachable — it sits after the `raise` statement with no control flow path to reach it.

**Fix:** Move experiment tracking into `execute()` (after `self.run()` returns).

#### Bug 3: `conftest.py:28` Uses `dev_project_id` — 60 Test Errors

**File:** `tests/conftest.py`
**Line:** 28
**Severity:** CRITICAL (causes 60 of 60 test errors)

```python
def mock_gcp_config() -> GCPConfig:
    return GCPConfig(
        dev_project_id="test-gcp-project",  # Wrong: field renamed to project_id
        region="us-central1",
    )
```

**Root cause:** PR #23 renamed `GCPConfig.dev_project_id` to `GCPConfig.project_id`. `GCPConfig` has `extra="ignore"` so the wrong field name is silently swallowed, and `project_id` (required, no default) raises `ValidationError`.

**Fix:** Change `dev_project_id=` to `project_id=` on line 28.

#### Bug 4: `bq_query.py:92-96` — AttributeError on Missing Fields

**File:** `gcp_ml_framework/components/operators/bq_query.py`
**Lines:** 92-96
**Severity:** CRITICAL (AttributeError at runtime)

`execute()` references `self.dataset`, `self.gcs_prefix`, `self.namespace` which DO NOT EXIST on `BQQuery` (they are `MLContext` fields, not `BaseComponent` fields). This will raise `AttributeError` at runtime for any direct invocation of `BQQuery.execute()`.

**Fix:** Remove or rework the references to use fields that actually exist on the component.

#### Bug 5: `third_run/` References — 4 Dockerfiles + 1 Import

**Severity:** CRITICAL (Docker builds fail, pipeline step import fails)

| File | Line | Reference |
|------|------|-----------|
| `docker/pipeline/Dockerfile` | 12 | `COPY third_run/ /app/third_run/` |
| `docker/train.Dockerfile` | 14 | `COPY third_run/ /app/third_run/` |
| `docker/serve.Dockerfile` | 15 | `COPY third_run/ /app/third_run/` |
| `docker/pipelines/house_price/base.Dockerfile` | 13 | `COPY third_run/ /app/third_run/` |
| `pipelines/house_price/steps/train_regression_model.py` | 15 | `from third_run.estimator import HousePredictionModel` |

Only `second_run/` directory exists.

#### Bug 6: Pipeline Definitions Use Removed `endpoint_name` Field

**Severity:** CRITICAL (deployments silently broken — empty endpoint name)

| File | Line | Issue |
|------|------|-------|
| `pipelines/training_pipeline/pipeline.py` | 67 | `endpoint_name="housing-predictor"` — should be `model_name="housing-predictor"` |
| `pipelines/verification_pipeline/pipeline.py` | 74 | `endpoint_name="verification-predictor"` — should be `model_name="verification-predictor"` |

`DeployModel` now derives the endpoint name from `model_name` via `vertex_endpoint_name(pipeline_name, model_name)`. The `endpoint_name` kwarg is silently swallowed by Pydantic's `extra="ignore"`.

#### Bug 7: `sync=False` Doc-Code Discrepancy — `register.py` vs `docs/register.md`

**File:** `gcp_ml_framework/components/ml/register.py`
**Severity:** CRITICAL (quota risk on shared GCP projects)

PR #26 removed `sync=False` from the `Model.upload()` kwargs, making the upload synchronous. However, `docs/register.md` (also PR #26) explicitly documents `sync=False` with rationale: sync=True polls the LRO via repeated GetOperation calls, consuming the 600 req/min CRUD quota. The docs represent the client's design intent. The code should re-add `sync=False`.

### 4.2 High Severity Bugs

#### Bug 8: `cache_enabled` Default Should Be `False` — `base.py:57`

**File:** `gcp_ml_framework/components/base.py`
**Line:** 57
**Severity:** HIGH (stale cache hits after teardown)

`cache_enabled: bool = True` should default to `False` per the 2026-03-06 caching fix. Cached steps return URIs to deleted BQ tables after teardown.

#### Bug 9: `enable_caching` Default Should Be `False` — `runner.py:29`

**File:** `gcp_ml_framework/pipeline/runner.py`
**Line:** 29
**Severity:** HIGH (same caching issue as Bug 8)

`enable_caching: bool = True` should default to `False` to match the RunPipelineJobOperator setting in generated DAGs.

#### Bug 10: `_INTERNAL_FIELDS` Dead `gcp_config` Reference — `base.py`

**File:** `gcp_ml_framework/components/base.py`
**Severity:** HIGH (misleading, no runtime error)

`_INTERNAL_FIELDS` contains `"gcp_config"` which does not exist as a field on `BaseComponent` or any subclass. Removed during config simplification in PR #23.

#### Bug 11: `cmd_init.py` .env Template Wrong Env Var Names

**File:** `gcp_ml_framework/cli/cmd_init.py`
**Lines:** 15-37
**Severity:** HIGH (scaffolded projects cannot read config)

The `.env` template uses `GML_TEAM` and `GML_PROJECT` but `FrameworkConfig` has `env_prefix=""` (reads `TEAM` and `PROJECT`). Also uses `GML_GCP__DEV_PROJECT_ID` etc. but `GCPConfig` has single `project_id` with `env_prefix="GCP_"`. Additionally, pipeline template at line 57 uses `DeployModel(endpoint_name=...)` — removed field.

#### Bug 12: `cloudbuild.yaml` References Legacy Dockerfiles

**File:** `cloudbuild.yaml`
**Severity:** HIGH (Cloud Build fails)

References `docker/pipeline/Dockerfile` and `docker/serving/Dockerfile` which are legacy files that should be removed per PR #26.

#### Bug 13: `email.py` Missing `__main__` Block

**File:** `gcp_ml_framework/components/operators/email.py`
**Severity:** HIGH (cannot invoke Email component via CLI)

Missing `if __name__ == "__main__": Email.cli()` block that other components have.

#### Bug 14: `cmd_deploy.py` Uses `import logging` Instead of Loguru

**File:** `gcp_ml_framework/cli/cmd_deploy.py`
**Severity:** HIGH (inconsistent with framework-wide loguru adoption)

Uses `import logging` instead of `from loguru import logger`, inconsistent with the 12 other files using loguru.

#### Bug 15: Legacy/Root-Level Dockerfiles Still Exist

**Severity:** HIGH (contradicts client's PR #26 design)

Files that should be removed per `docs/deploy.md`:

| File | Reason |
|------|--------|
| `docker/train.Dockerfile` | Root-level default, client says removed |
| `docker/serve.Dockerfile` | Root-level default, client says removed |
| `docker/pipeline/Dockerfile` | Legacy unified image, superseded |
| `docker/serving/Dockerfile` | Legacy serving image, superseded |
| `docker/pipelines/house_price/train.Dockerfile` | Client target: only `base.Dockerfile` + `serve.Dockerfile` per pipeline |

### 4.3 Medium Severity Bugs

#### Bug 16: `smart_compiler.py:25,33` — Uses `@dataclass` Instead of Pydantic

**File:** `gcp_ml_framework/pipeline/smart_compiler.py`
**Lines:** 25, 33
**Severity:** MEDIUM (REQS 7.0 violation)

`CompilationResult` and `_StepGroup` use `@dataclass` instead of Pydantic `BaseModel`. Only remaining `@dataclass` usage in the framework.

#### Bug 17: `naming.py:36-39` — Generic Exception Catching

**File:** `gcp_ml_framework/naming.py`
**Lines:** 36-39
**Severity:** MEDIUM (masks real errors)

`get_git_branch()` catches generic `Exception` instead of specific exceptions like `subprocess.SubprocessError`, `KeyError`.

#### Bug 18: `bq_query.py:129` — Unsafe SQL String Escaping

**File:** `gcp_ml_framework/components/operators/bq_query.py`
**Line:** 129
**Severity:** MEDIUM (potential SQL injection in generated DAGs)

SQL values are escaped via simple string replacement rather than parameterized queries.

#### Bug 19: `context.py:96` — Field Declared After Frozen Model Methods

**File:** `gcp_ml_framework/context.py`
**Line:** 96
**Severity:** MEDIUM (architecturally surprising, works but fragile)

`pipeline_service_account_email` is declared at line 96, after `@property` methods, in a `frozen=True` model. Valid Pydantic but breaks reading expectations.

#### Bug 20: `conftest.py:35` — Wrong Env Var Prefix

**File:** `tests/conftest.py`
**Line:** 35
**Severity:** MEDIUM (`"GML_ENVIRONMENT"` should be `"ENVIRONMENT"`)

`FrameworkConfig` uses `env_prefix=""`, so the correct env var is `ENVIRONMENT`, not `GML_ENVIRONMENT`.

#### Bug 21: `bq_query.py:146` — Hardcoded `gcp_conn_id`

**File:** `gcp_ml_framework/components/operators/bq_query.py`
**Line:** 146
**Severity:** MEDIUM (not configurable for environments with non-default Airflow connections)

`gcp_conn_id="google_cloud_default"` is hardcoded rather than configurable.

---

## 5. Test Failure Root Causes

**Total: 61 failures + 60 errors = 121 broken tests out of 226 selected.**

| Root Cause | Count | Type | Affected Tests |
|------------|-------|------|----------------|
| conftest `dev_project_id` -> `project_id` | 60 | ERROR | All tests using `mock_gcp_config` fixture: cli/ (7), bq_query (3), bq_transform (5), email (4), write_features (2), context (7), compiler (6), local_runner (5), smart_compiler (16), training_pipeline (1), verification_pipeline (6) |
| Decorator `._task_type` -> `.task_type` | 12 | FAIL | test_decorators (7), test_bq_query (1), test_bq_transform (1), test_email (1), test_write_features (1), test_base (1) |
| DeployModel field renames | 9 | FAIL | test_deploy (9) — tests expect `endpoint_name`, `model_uri`, `serving_container_image` fields |
| Config multi-env project IDs | 9 | FAIL | test_config (9) — tests expect `dev_project_id`, `staging_project_id`, `prod_project_id` on GCPConfig |
| Vertex utils old `run_deploy()` signature | 9 | FAIL | test_vertex (9) — tests expect `model_uri`, `serving_container_image`, `endpoint_name` params |
| TrainModel lifecycle | 4 | FAIL | test_train (4) — tests expect `_work_dir`, `hyperparameters`, `trainer_args` fields |
| Pipeline definition step counts | 4 | FAIL | test_steps (4) — training_pipeline step count/name assertions |
| Pipeline task types | 4 | FAIL | test_compile (4) — verification_pipeline step count/name assertions |
| RegisterModel CPR routes removed | 2 | FAIL | test_register (2) — tests expect CPR kwarg handling |
| Unified builder task_type access | 2 | FAIL | test_unified_builder (2) — tests access `._task_type` instead of `.task_type` |
| Context is_production | 2 | FAIL | test_context (2) — need mock_gcp_config fix first |
| Smart compiler schedule + grouping | 3 | FAIL | test_smart_compiler (3) — schedule rendering and group counting |
| Internal fields set outdated | 1 | FAIL | test_base (1) — expected `_INTERNAL_FIELDS` set mismatch |

---

## 6. GCP Best Practices Assessment

### Following

| Practice | Evidence |
|----------|----------|
| `RunPipelineJobOperator` (correct, not `CreatePipelineJobOperator`) | Compiler DAG generation |
| `template_fields` extension for Jinja rendering | Generated DAGs extend `RunPipelineJobOperator.template_fields` |
| Artifact Registry (not deprecated Container Registry) | All image URIs use `*-docker.pkg.dev` |
| Cloud Build with layer caching (`--cache-from` pattern) | `cloudbuild.yaml` |
| Feature Store v2 (BQ-native) with `v1beta1` for FeatureGroup | `feature_store/client.py` |
| BigQuery v3.25+ (modern jobs API) | `pyproject.toml` dependencies |
| `google-cloud-aiplatform>=1.136` | `pyproject.toml` |
| GCS bucket naming with project ID for global uniqueness | `NamingConvention.gcs_bucket()` |
| Branch-isolated GCS prefixes | `NamingConvention.gcs_prefix()` |
| Service account impersonation pattern in Composer | `RunPipelineJobOperator` `service_account` field |

### Gaps

| Gap | Severity | Detail |
|-----|----------|--------|
| No uniform bucket-level access configured | LOW | GCS best practice for simplified ACLs |
| No lifecycle rules on GCS | LOW | Cost management — old pipeline artifacts accumulate |
| No AR cleanup/vulnerability scanning policies | LOW | Image sprawl over time |
| Secret Manager client lacks response caching | LOW | Repeated lookups for same secrets |
| AR operations use `subprocess`/`gcloud` CLI instead of `google-cloud-artifactregistry` SDK | MEDIUM | `utils/ar.py` shells out to `gcloud artifacts docker tags` |
| Generic `Exception` catching | MEDIUM | Should catch `google.api_core.exceptions.NotFound` etc. specifically |
| `enable_caching` defaults wrong (True instead of False) | HIGH | `base.py:57`, `runner.py:29` — contradicts 2026-03-06 fix |
| `cloudbuild.yaml` references legacy Dockerfiles | HIGH | `docker/pipeline/Dockerfile` and `docker/serving/Dockerfile` |

---

## 7. Docker Image Pattern

### Current State (Incorrect)

```
docker/
+-- base/base-python/Dockerfile       <-- Foundation (CORRECT - keep)
+-- train.Dockerfile                   <-- Root default (REMOVE per PR #26)
+-- serve.Dockerfile                   <-- Root default (REMOVE per PR #26)
+-- pipeline/Dockerfile                <-- Legacy (REMOVE per PR #26)
+-- serving/Dockerfile                 <-- Legacy (REMOVE per PR #26)
+-- pipelines/
    +-- house_price/
        +-- base.Dockerfile            <-- Per-pipeline execution (CORRECT - keep)
        +-- train.Dockerfile           <-- Extra (REMOVE - client target is base+serve only)
        +-- serve.Dockerfile           <-- Per-pipeline serving (CORRECT - keep)
```

### Target State (Per Client PR #26)

```
docker/
+-- base/base-python/Dockerfile       <-- Tier 0: Foundation (built once)
+-- pipelines/
    +-- house_price/
        +-- base.Dockerfile            <-- Tier 1: Per-pipeline execution
        +-- serve.Dockerfile           <-- Tier 1: Per-pipeline serving
```

### Image Count Patterns

| Pipeline Type | Images | Dockerfiles |
|---------------|--------|-------------|
| Simplest (eval-only, no serving) | 2 | `base.Dockerfile` + `serve.Dockerfile` |
| Typical (train + serve) | 3 | `base.Dockerfile` + `train.Dockerfile` + `serve.Dockerfile` |
| Multi-model (N models) | 1 + 2N | `base.Dockerfile` + N x (`train.Dockerfile` + `serve.Dockerfile`) |

The current client target is the simplest pattern: 2 Dockerfiles per pipeline (`base.Dockerfile` for execution, `serve.Dockerfile` for serving). The `base-python` foundation image is shared across all pipelines.

---

## 8. Prioritized Action Items

Detailed plan with checkboxes, file paths, and verification commands: `docs/tasks/todo.md`

| Phase | Focus | Impact | Key Tasks |
|-------|-------|--------|-----------|
| 1 | Critical Runtime Bugs | Unblocks compilation and deployment | Delete `serving_image` block, fix dead code in train.py, fix `third_run` refs, fix `bq_query.py` AttributeError, fix pipeline `endpoint_name` |
| 2 | Ruff Compliance | Code quality baseline | 19 -> 0 lint errors |
| 3 | Test Infrastructure | 60 errors resolved | Fix conftest `dev_project_id` -> `project_id`, fix env var prefix |
| 4 | Test Fixes by Root Cause | 61 -> 0 failures | Decorator attrs, DeployModel fields, Config fields, Vertex utils, TrainModel lifecycle |
| 5 | Config, Scaffolding & Defaults | Correct scaffolding + caching | Fix `cmd_init.py` templates, fix `cache_enabled` defaults, fix `bq_query.py` execute |
| 6 | Pydantic Migration & Cleanup | REQS 7.0 compliance | `@dataclass` -> `BaseModel`, dead code removal, email `__main__`, logging consistency |
| 7 | Docker Cleanup & Cloud Build | PR #26 compliance | Remove legacy Dockerfiles, update `cloudbuild.yaml`, re-add `sync=False`, fix tags |
| 8 | New Capabilities | REQS coverage | Loguru 9.0, Loop/Condition 22.0, Mypy 17.0, DBT 19.0, Docs 10.0+20.0, GCP best practices |
