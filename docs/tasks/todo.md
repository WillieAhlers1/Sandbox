# version_1 Development Roadmap — Post-PR #25 Reconciliation

**Date:** 2026-03-22
**Status:** Phases 1–5.5 code exists, but PR #25 restructured components/compiler/Docker without updating tests.
**Branch:** version_1
**Focus:** Dev environment only. No CI/CD. Data scientist journey + platform correctness.
**Test baseline:** 105 pass, 61 fail, 60 errors out of 228 unit tests.
**Target:** All tests pass, 0 lint errors, full compile + local run working.
**USE UV FOR PYTHON and ENSURE RUFF HAS NO ERRORS WHEN EVER DEALING WITH PYTHON CODE**

---

## What PR #25 Changed (context for this plan)

| Change | Before | After |
|--------|--------|-------|
| BaseComponent image field | `image_name: str = ""` | `runtime_dockerfile: str = ""` |
| RegisterModel serving image | `serving_container_image` only | `serving_dockerfile` + `serving_container_image` (full URI override) |
| DeployModel fields | `endpoint_name` (required), `model_uri`, `serving_container_image` | `model_name` only — endpoint auto-derived |
| `run_deploy()` | Uploads model + deploys | Looks up registered model by display name, deploys |
| `vertex_endpoint_name()` | `(model_name)` | `(pipeline_name, model_name)` |
| Docker serving | Generic `docker/serving/Dockerfile` | Per-pipeline `docker/pipelines/{name}/serve.Dockerfile` + FastAPI apps |
| Compiler image resolution | `_resolve_image_uri(context, pipeline_name, image_name)` | `_resolve_image_uri(context, dockerfile_path)` with `_parse_dockerfile_path()` |

**Tests NOT updated by PR #25** — all test failures are from old expectations against new code.

---

## Group 1: Docker & File References

### 1.1 Fix `third_run` → `second_run`

**Problem:** Multiple Dockerfiles and one pipeline import reference `third_run/` but only `second_run/` exists.

**Files:**
- [ ] `docker/pipeline/Dockerfile` — `COPY third_run/` → `COPY second_run/`
- [ ] `docker/train.Dockerfile` — `COPY third_run/` → `COPY second_run/`
- [ ] `docker/serve.Dockerfile` — `COPY third_run/` → `COPY second_run/` (if file still exists)
- [ ] `docker/pipelines/house_price/base.Dockerfile` — `COPY third_run/` → `COPY second_run/`
- [ ] `pipelines/house_price/steps/train_regression_model.py` — `from third_run.estimator` → `from second_run.estimator`

**DOD:** `grep -r "third_run" --include="*.py" --include="Dockerfile*" .` returns nothing (excluding docs).

---

## Group 2: Configuration & Environment

### 2.1 Fix `cmd_init.py` .env Template

**Problem:** `gml init project` generates env vars (`GML_TEAM`, `GML_GCP__DEV_PROJECT_ID`) that the framework can't read. FrameworkConfig uses `env_prefix=""`, GCPConfig uses `env_prefix="GCP_"`.

**Files:**
- [ ] `gcp_ml_framework/cli/cmd_init.py` — Update `_DOT_ENV`: `GML_TEAM` → `TEAM`, `GML_PROJECT` → `PROJECT`, `GML_ENVIRONMENT` → `ENVIRONMENT`, `GML_GCP__DEV_PROJECT_ID` → `GCP_PROJECT_ID`, `GML_GCP__REGION` → `GCP_REGION`. Remove staging/prod project IDs. Remove `--staging-project`/`--prod-project` args from `init_project()`.
- [ ] `.env.example` — Match actual env var names. Remove derived vars (`GCP_AR_HOST`, `GCP_AR_REPO`).

**DOD:** `UV_ENV_FILE=.env uv run -- gml context show` displays correct values.

### 2.2 Fix `get_git_branch()` KeyError Risk

**File:**
- [ ] `gcp_ml_framework/naming.py:36` — `os.environ['ENVIRONMENT']` → `os.environ.get('ENVIRONMENT', 'local')`

**DOD:** No KeyError when ENVIRONMENT env var is missing.

### 2.3 Fix `context.py` Duplicate Field

**File:**
- [ ] `gcp_ml_framework/context.py` — Remove duplicate `pipeline_service_account_email` declaration at line 96.

### 2.4 Update CLAUDE.md

- [ ] Fix env var name references (`GML_ENVIRONMENT` → `ENVIRONMENT`, etc.)
- [ ] Document `runtime_dockerfile` and `serving_dockerfile` fields
- [ ] Note per-pipeline Docker strategy

---

## Group 3: Component System

### 3.1 Fix TrainModel: Dead Code + Restore `execute()` Lifecycle

**Problem:** Experiment tracking code (lines 77-104) is after `raise NotImplementedError` — dead code. `execute()` doesn't create temp dir or set `_work_dir`. Missing `hyperparameters` and `trainer_args` fields.

**File:**
- [ ] `gcp_ml_framework/components/ml/train.py`
  - Add: `hyperparameters: dict = Field(default_factory=dict)`, `trainer_args: list[str] = Field(default_factory=list)`
  - Rewrite `execute()`: create `tempfile.TemporaryDirectory`, set `self._work_dir`, call `self.run()`, handle None return (fallback to `_work_dir`), upload to GCS, write output URI, experiment tracking (moved from dead `run()` code)
  - Clean `run()`: just docstring + `raise NotImplementedError`, delete dead code after it

**DOD:** `uv run -- pytest tests/components/test_train.py -m unit -v` — all pass.

### 3.2 Add `__main__` Blocks to BQQuery and Email

**Files:**
- [ ] `gcp_ml_framework/components/operators/bq_query.py` — append `if __name__ == "__main__": BQQuery.cli()`
- [ ] `gcp_ml_framework/components/operators/email.py` — append `if __name__ == "__main__": Email.cli()`

**DOD:** `uv run -- python -m gcp_ml_framework.components.operators.bq_query --help` works.

### 3.3 Fix WriteFeatures `render_operator()` — Invalid DAG

**Problem:** Generates `PythonOperator(python_callable=_write_features_X)` but never defines that function.

**File:**
- [ ] `gcp_ml_framework/components/feature_store/write_features.py` — Generate both function definition and operator reference.

**DOD:** Pipeline with WriteFeatures compiles to valid Python DAG.

### 3.4 Clean `_INTERNAL_FIELDS`

**Problem:** Contains `"gcp_config"` (dead reference). Now has `"runtime_dockerfile"` and `"serving_dockerfile"` which is correct.

**File:**
- [ ] `gcp_ml_framework/components/base.py` — Remove `"gcp_config"` from `_INTERNAL_FIELDS`.

**DOD:** Every entry in `_INTERNAL_FIELDS` corresponds to an actual field.

---

## Group 4: Pipeline Compilation

### 4.1 Fix `compiler.py` — `serving_image` NameError (STILL EXISTS post-PR #25)

**Problem:** `_build_derived_params()` has a block referencing undefined `serving_image`. RegisterModel is already handled above it. DeployModel no longer needs serving image (looks up registered model). This block is redundant AND broken.

**File:**
- [ ] `gcp_ml_framework/pipeline/compiler.py` — Delete the `isinstance(comp, (RegisterModel, DeployModel))` block with `serving_image` reference entirely.

**DOD:** `UV_ENV_FILE=.env uv run -- gml compile --all` completes without NameError.

### 4.2 Remove Dead Context Params from Compiler

**Problem:** `_build_context_params()` returns `gcs_prefix`, `staging_bucket`, `feature_store_id`, `artifact_registry` — none are BaseComponent fields, silently filtered out.

**File:**
- [ ] `gcp_ml_framework/pipeline/compiler.py` — Remove dead params from returned dict.

### 4.3 Convert `smart_compiler.py` @dataclass → Pydantic

**File:**
- [ ] `gcp_ml_framework/pipeline/smart_compiler.py` — Convert `CompilationResult` and `_StepGroup` to Pydantic `BaseModel`.

**DOD:** `grep -r "@dataclass" gcp_ml_framework/` returns nothing.

---

## Group 5: Test Infrastructure

### 5.1 Fix `conftest.py` Fixture (60 errors)

- [ ] `tests/conftest.py:28` — `dev_project_id=` → `project_id=`

### 5.2 Fix Decorator Tests — `_task_type` → `task_type` (12 failures)

- [ ] `tests/components/test_decorators.py` — All `._task_type` → `.task_type`, update default expectation
- [ ] `tests/components/test_bq_query.py`, `test_bq_transform.py`, `test_email.py`, `test_write_features.py` — same
- [ ] `tests/pipeline/test_unified_builder.py` — Fix task type expectations
- [ ] `gcp_ml_framework/pipeline/builder.py:98` — Fallback `TaskType.ML_TASK` → `TaskType.TASK`

### 5.3 Fix Config Tests (9 failures)

- [ ] `tests/config/test_config.py` — Rewrite for single `project_id` model
- [ ] `tests/config/test_context.py` — `dev_project_id`/`prod_project_id` → `project_id`

### 5.4 Fix `_INTERNAL_FIELDS` Test

- [ ] `tests/components/test_base.py` — Update expected set: `runtime_dockerfile`, `serving_dockerfile`, `model_name` (no `image_name`, no `gcp_config`)

### 5.5 Fix DeployModel Tests (9 failures — from PR #25 field changes)

- [ ] `tests/components/test_deploy.py` — Rewrite for new fields (`model_name` instead of `endpoint_name`/`model_uri`/`serving_container_image`). Update `run_deploy()` mock signature.

### 5.6 Fix Vertex Utils Tests (9 failures — `run_deploy()` signature changed)

- [ ] `tests/utils/test_vertex.py` — Rewrite for new `run_deploy()` (looks up by display_name, no model_uri/serving_container_image params). Remove CPR tests. Update monitoring tests.

### 5.7 Fix RegisterModel Tests (2 failures — CPR removed)

- [ ] `tests/components/test_register.py` — Remove CPR assertions from execute test. Delete `TestRegisterModelCPR` class.

### 5.8 Fix Pipeline Definition Tests (8 failures — step count changes)

- [ ] `tests/training_pipeline/test_steps.py` — Update for 1-step pipeline (was 6)
- [ ] `tests/verification_pipeline/test_compile.py` — Update step count, names, types

### 5.9 Fix Smart Compiler Tests

- [ ] `tests/pipeline/test_smart_compiler.py` — Fix GCPConfig fields. Verify after compiler/decorator fixes.

### 5.10 Fix Compiler Tests (3 errors)

- [ ] `tests/pipeline/test_compiler.py` — Rewrite `TestBuildDerivedParamsServingImage` for `serving_dockerfile` and new `_resolve_image_uri(context, dockerfile_path)` API.

---

## Group 6: Generated Artifacts

### 6.1 Regenerate DAGs and Compiled Pipelines

- [ ] Delete all files in `dags/` and `compiled_pipelines/`
- [ ] Run `UV_ENV_FILE=.env uv run -- gml compile --all`

---

## Group 7: Conditional & Loop Operators (REQS 22.0 [P0])

### 7.1 Design Document
- [ ] `docs/design_loop_condition.md` — DS API, KFP mapping, Airflow limitations, examples

### 7.2 Extend Pipeline Builder
- [ ] `gcp_ml_framework/pipeline/builder.py` — Add `Pipeline.for_each()` and condition support

### 7.3 KFP Compilation
- [ ] `gcp_ml_framework/pipeline/compiler.py` — `dsl.ParallelFor` / `dsl.Condition` support

### 7.4 Airflow Handling
- [ ] `gcp_ml_framework/pipeline/smart_compiler.py` — Unroll @task loops or raise clear error

### 7.5 Tests
- [ ] `tests/pipeline/test_builder_loops.py`, `tests/pipeline/test_compiler_loops.py`

---

## Group 8: Type Safety — Mypy (REQS 17.0)

### 8.1 Configuration
- [ ] `pyproject.toml` — Add `[tool.mypy]`, add `types-PyYAML`

### 8.2 Fix Errors (~19 across 7 files)
- [ ] `decorators.py`, `base.py`, `config.py`, `secrets/client.py`, `compiler.py`, `register.py`, `feature_store/schema.py`

**DOD:** `uv run -- mypy gcp_ml_framework/` — 0 errors.

---

## Group 9: DBT Integration (REQS 19.0)

### 9.1 Create DBTRun Component
- [ ] `gcp_ml_framework/components/transformation/dbt_run.py` — `@task` with `render_operator()` → `BashOperator`
- [ ] Export from `__init__.py`

### 9.2 Tests
- [ ] `tests/components/test_dbt_run.py`

### 9.3 Composer Verification
- [ ] Deploy test pipeline with DBT step, verify DAG parses

---

## Group 10: Documentation (REQS 10.0, 20.0)

### 10.1 Google-Style Docstrings
- [ ] Missing docstrings on Email methods, compiler/builder public methods, `load_config()`

### 10.2 Create AGENTS.md
- [ ] Architecture, components, pipelines, testing, pitfalls, configuration

---

## Execution Order

```
Phase A — Fix broken things:
  Group 1 (Docker)      → standalone
  Group 2 (Config)      → standalone
  Group 3 (Components)  → standalone
  Group 4 (Compilation) → standalone
  Group 5 (Tests)       → depends on Groups 1-4
  Group 6 (Artifacts)   → depends on Groups 2, 4

Phase B — New capabilities:
  Group 7  (Loop/Condition) → depends on Phase A
  Group 9  (DBT)            → depends on Group 3
  Group 8  (Mypy)           → depends on Phase A
  Group 10 (Docs)           → depends on all above
```

**Recommended order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 9 → 8 → 10

---

## Final Verification

```bash
# Phase A
uv run -- pytest tests/ -m unit -v
uv run -- ruff check gcp_ml_framework tests
UV_ENV_FILE=.env uv run -- gml context show
UV_ENV_FILE=.env uv run -- gml compile --all
grep -r "third_run" --include="*.py" --include="Dockerfile*" .
grep -r "@dataclass" gcp_ml_framework/

# Phase B
uv run -- mypy gcp_ml_framework/
uv run -- pytest tests/components/test_dbt_run.py -m unit -v
test -f AGENTS.md
```

---

## Not In Scope

| Item | REQS | Reason |
|------|------|--------|
| CI/CD pipeline setup | 16.0 [P1] | Explicitly out of scope per user direction |
