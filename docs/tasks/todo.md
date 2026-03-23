# version_1_enc Development Roadmap

**Date:** 2026-03-23
**Branch:** version_1_enc
**Focus:** DEV environment only. No CI/CD. No over-engineering.
**Test baseline:** 61 failed, 105 passed, 60 errors (228 total)
**Ruff baseline:** 19 errors
**Target:** 0 test failures, 0 test errors, 0 ruff errors, full compile working.

### Client Design Principles (PRs #23-#26 -- ALWAYS FOLLOW)

These are **non-negotiable** design decisions established by the client:

1. **`NamingConvention` is single source of truth** for all GCP resource names. Python and bash both delegate to it.
2. **`RegisterModel` is the SINGLE OWNER of the serving container image.** `DeployModel` does NOT have serving image fields.
3. **`model_name` is the CONTRACT** between `RegisterModel` and `DeployModel`. Links registration to deployment.
4. **Two Dockerfiles per pipeline:** `base.Dockerfile` (execution) + `serve.Dockerfile` (serving). Root-level defaults removed.
5. **Docker image naming:** `{pipeline}--{stem}` delimiter. `NamingConvention.docker_image_name()` only.
6. **Config simplified:** Single `GCP_PROJECT_ID` (not per-env). `env_prefix=""` for framework, `env_prefix="GCP_"` for GCP.
7. **Registration vs Deployment separation:** RegisterModel captures image. DeployModel looks up registered model. No duplication.
8. **Component lifecycle:** `cli()` -> `execute()` -> `run()`. Data scientists override `run()` only.
9. **Generated DAGs must have ZERO `gcp_ml_framework` imports.** Self-contained Python.
10. **`sync=False` on `Model.upload()`** to avoid CRUD quota exhaustion on shared projects.

See `docs/register.md` and `docs/deploy.md` for full design rationale.

---

## Phase 1: Critical Runtime Bugs & Dead Code Removal

**REQS:** Regression fixes from 1.0 implementation
**Why first:** Nothing else works until these are fixed.

### 1.1 Delete `serving_image` NameError block in compiler (Bug 1)

**Problem:** `_build_derived_params()` references undefined variable `serving_image` at line 307 (F821). RegisterModel serving image resolution is already handled at lines 280-290 (three-tier priority). DeployModel no longer needs a serving image. This block is both redundant and broken.

**Files:**
- [ ] `gcp_ml_framework/pipeline/compiler.py` lines 305-307 -- delete the entire block:
  ```python
  if isinstance(comp, (RegisterModel, DeployModel)):
      if not comp.serving_container_image:
          extra["serving_container_image"] = serving_image
  ```

**Verification:**
```bash
uv run -- ruff check gcp_ml_framework/pipeline/compiler.py | grep F821
# Expected: no output
uv run -- python -c "from gcp_ml_framework.pipeline.compiler import PipelineCompiler; print('OK')"
```

### 1.2 Fix dead code in train.py (Bug 2)

**Problem:** Lines 77-104 in `train.py` are unreachable -- they appear after `raise NotImplementedError` at line 71 inside `run()`. This is experiment tracking code that should execute after `self.run()` completes in `execute()`.

**Files:**
- [ ] `gcp_ml_framework/components/ml/train.py`
  - Delete lines 76-104 (dead code block after `raise NotImplementedError`)
  - Move experiment tracking into `execute()`, after the GCS upload block completes (after line 62)
  - The `run()` method should contain only the docstring + `raise NotImplementedError`

**Verification:**
```bash
uv run -- python -c "
import ast
with open('gcp_ml_framework/components/ml/train.py') as f:
    tree = ast.parse(f.read())
print('OK')
"
```

### 1.3 Fix `third_run` references (Bug 5)

**Problem:** Multiple files reference `third_run/` but only `second_run/` exists.

**Files to fix (keeping these):**
- [ ] `docker/pipelines/house_price/base.Dockerfile:13` -- `COPY third_run/ /app/third_run/` -> `COPY second_run/ /app/second_run/`
- [ ] `pipelines/house_price/steps/train_regression_model.py:15` -- `from third_run.estimator` -> `from second_run.estimator`

**Files NOT fixed here (deleted in Phase 7.1):**
- `docker/pipeline/Dockerfile:12` -- will be deleted
- `docker/train.Dockerfile:14` -- will be deleted
- `docker/serve.Dockerfile:15` -- will be deleted

**Verification:**
```bash
grep -r "third_run" --include="*.py" --include="Dockerfile*" docker/ pipelines/
# Expected: no output
```

### 1.4 Fix `bq_query.py` AttributeError in `execute()` (Bug 4)

**Problem:** `bq_query.py:92-96` `execute()` references `self.dataset`, `self.gcs_prefix`, `self.namespace` which DO NOT EXIST on `BQQuery`. These are `MLContext` fields, not `BaseComponent` fields. Will raise `AttributeError` at runtime.

**Files:**
- [ ] `gcp_ml_framework/components/operators/bq_query.py` lines 92-96 -- remove or rework the references to use fields that actually exist on the component (e.g., `self.project`, `self.region`, `self.run_date`)

**Verification:**
```bash
uv run -- python -c "
from gcp_ml_framework.components.operators.bq_query import BQQuery
# Verify no reference to non-existent fields in execute()
import inspect
src = inspect.getsource(BQQuery.execute)
for attr in ['self.dataset', 'self.gcs_prefix', 'self.namespace']:
    assert attr not in src, f'{attr} still referenced in execute()'
print('OK')
"
```

### 1.5 Fix `_INTERNAL_FIELDS` dead reference (Bug 10)

**Problem:** `_INTERNAL_FIELDS` in `base.py` contains `"gcp_config"` which is not a field on `BaseComponent`.

**Files:**
- [ ] `gcp_ml_framework/components/base.py` line 28 -- remove `"gcp_config"` from `_INTERNAL_FIELDS`

**Verification:**
```bash
uv run -- python -c "
from gcp_ml_framework.components.base import _INTERNAL_FIELDS, BaseComponent
for f in _INTERNAL_FIELDS:
    assert f in BaseComponent.model_fields, f'{f} is not a BaseComponent field'
print('All _INTERNAL_FIELDS are valid')
"
```

### 1.6 Fix pipeline definitions using removed `endpoint_name=` (Bug 6)

**Problem:** `DeployModel` no longer has an `endpoint_name` field (replaced by `model_name` in PR #25). Two pipeline definitions still use `endpoint_name=`. Because `BaseComponent` uses `extra="ignore"` from `BaseSettings`, these are silently dropped.

**Confirmed locations:**
- [ ] `pipelines/training_pipeline/pipeline.py` line 67 -- `endpoint_name="housing-predictor"` -> `model_name="housing-predictor"`
- [ ] `pipelines/verification_pipeline/pipeline.py` line 74 -- `endpoint_name="verification-predictor"` -> `model_name="verification-predictor"`

**Note:** `pipelines/house_price/pipeline.py` already uses `model_name="regression"` correctly.

**Verification:**
```bash
uv run -- python -c "from pipelines.training_pipeline.pipeline import pipeline; print('training OK')"
uv run -- python -c "from pipelines.verification_pipeline.pipeline import pipeline; print('verification OK')"
grep -rn "endpoint_name=" pipelines/*/pipeline.py
# Expected: no output
```

### 1.7 Fix `get_git_branch()` generic Exception catching (Bug 17)

**Problem:** `naming.py:36-39` catches generic `Exception`, masking real errors. The function should catch specific exceptions.

**Files:**
- [ ] `gcp_ml_framework/naming.py` lines 36-39 -- change `except Exception:` to `except (subprocess.SubprocessError, KeyError, OSError):`
- [ ] `gcp_ml_framework/naming.py` line 36 -- `os.environ['ENVIRONMENT']` -> `os.environ.get('ENVIRONMENT', 'local')`

**Verification:**
```bash
uv run -- python -c "
import os
os.environ.pop('ENVIRONMENT', None)
from gcp_ml_framework.naming import get_git_branch
result = get_git_branch()
print(f'Branch: {result}')
"
```

### Phase 1 Definition of Done

- [ ] `uv run -- ruff check gcp_ml_framework/pipeline/compiler.py | grep F821` returns nothing
- [ ] `grep -r "third_run" --include="*.py" --include="Dockerfile*" docker/ pipelines/` returns nothing
- [ ] `grep -rn "endpoint_name=" pipelines/*/pipeline.py` returns nothing
- [ ] All pipeline definitions import without error
- [ ] `get_git_branch()` works without KeyError when ENVIRONMENT is unset
- [ ] `bq_query.py` `execute()` has no references to `self.dataset`, `self.gcs_prefix`, `self.namespace`

**Verification:**
```bash
uv run -- ruff check gcp_ml_framework/pipeline/compiler.py | grep F821
grep -r "third_run" --include="*.py" --include="Dockerfile*" docker/ pipelines/
grep -rn "endpoint_name=" pipelines/*/pipeline.py
uv run -- python -c "from pipelines.house_price.pipeline import pipeline; print('house_price OK')"
uv run -- python -c "from pipelines.training_pipeline.pipeline import pipeline; print('training OK')"
uv run -- python -c "from pipelines.verification_pipeline.pipeline import pipeline; print('verification OK')"
```

---

## Phase 2: Ruff Compliance (19 -> 0)

**REQS:** Code quality baseline
**Current errors (19 total):**
- I001 x7 (import sorting): `__init__.py`, `base.py`, `register.py`, `naming.py`, `decorators.py`, `house_price/pipeline.py`, `train_regression_model.py`
- W293 x1 (whitespace): `base.py:81`
- W291 x1 (trailing whitespace): `naming.py:38`
- F401 x2 (unused imports): `config.py:18` (`model_validator`), `decorators.py:10` (`BaseComponent`)
- E501 x4 (line too long): `config.py:47`, `config.py:92`, `naming.py:222`, `compiler.py:83`
- F821 x1 (undefined name): `compiler.py:307` (fixed in Phase 1.1)
- UP035 x1 (deprecated import): `decorators.py:5`
- UP047 x3 (generic function should use type params): `decorators.py:15,32,43`

### 2.1 Auto-fix import sorting and whitespace

- [ ] Run `uv run -- ruff check --fix gcp_ml_framework/` to fix I001 (x7), W293 (x1), W291 (x1)

**Fixes 9 errors automatically.**

### 2.2 Fix unused imports (F401)

- [ ] `gcp_ml_framework/config.py:18` -- remove `model_validator` from `from pydantic import BaseModel, Field, model_validator`
- [ ] `gcp_ml_framework/decorators.py:10` -- remove entire `from gcp_ml_framework.components.base import BaseComponent` line (in TYPE_CHECKING block, but ruff says unused)

### 2.3 Fix line too long (E501)

- [ ] `gcp_ml_framework/config.py:47` (130 chars) -- break the `pipeline_service_account_email` Field line
- [ ] `gcp_ml_framework/config.py:92` (124 chars) -- break the `feature_store` Field line
- [ ] `gcp_ml_framework/naming.py:222` (101 chars) -- shorten docstring example line
- [ ] `gcp_ml_framework/pipeline/compiler.py:83` (110 chars) -- break the `_build_derived_params()` call across lines

### 2.4 Fix deprecated import (UP035)

- [ ] `gcp_ml_framework/decorators.py:5` -- change `from typing import TYPE_CHECKING, Callable, TypeVar, overload` to import `Callable` from `collections.abc` instead

### 2.5 Fix generic function type params (UP047)

- [ ] `gcp_ml_framework/decorators.py` lines 15, 32, 43 -- convert `TypeVar("_C")` pattern to Python 3.12+ type parameter syntax, or suppress with `# noqa: UP047` if the refactor is too invasive for the overload pattern

**Note:** F821 (`serving_image`) is already fixed in Phase 1.1.

### Phase 2 Definition of Done

- [ ] `uv run -- ruff check gcp_ml_framework tests` returns `Found 0 errors.` (or `All checks passed!`)

**Verification:**
```bash
uv run -- ruff check gcp_ml_framework tests
```

---

## Phase 3: Test Infrastructure (conftest -- 60 errors)

**REQS:** Testing baseline
**Why:** 60 of 228 tests error before even running because `conftest.py` fixtures create GCPConfig with removed fields.

### 3.1 Fix `mock_gcp_config` fixture (Bug 3)

**Problem:** `tests/conftest.py:28` creates `GCPConfig(dev_project_id="test-gcp-project")`. GCPConfig now has `project_id`, not `dev_project_id`. Because `extra="ignore"` is set, the kwarg is silently dropped, leaving `project_id` unset.

**Files:**
- [ ] `tests/conftest.py` line 28 -- `dev_project_id="test-gcp-project"` -> `project_id="test-gcp-project"`

### 3.2 Fix `mock_framework_config` env var (Bug 20)

**Problem:** `tests/conftest.py:35` sets `"GML_ENVIRONMENT": "dev"` in env vars. FrameworkConfig uses `env_prefix=""`, so the correct env var is `ENVIRONMENT`, not `GML_ENVIRONMENT`.

**Files:**
- [ ] `tests/conftest.py` line 35 -- `"GML_ENVIRONMENT": "dev"` -> `"ENVIRONMENT": "dev"`

### Phase 3 Definition of Done

- [ ] `uv run -- pytest tests/config/test_context.py -m unit -v` -- all pass (no errors)
- [ ] Test error count drops from 60 to near zero
- [ ] `uv run -- python -c "from tests.conftest import *; print('OK')"` works

**Verification:**
```bash
uv run -- pytest tests/config/test_context.py -m unit -v
uv run -- pytest tests/ -m unit --co -q 2>&1 | tail -5
```

---

## Phase 4: Test Fixes by Root Cause (61 -> 0)

**REQS:** Verification of 1.0, 7.0, 8.0, 11.0, 13.0, 15.0, 21.0

### 4.1 Decorator attribute name (12+ failures)

**Problem:** Tests in `test_decorators.py` use `._task_type` (private attribute) but the actual attribute is `.task_type` (ClassVar on BaseComponent, set by decorators).

**Files:**
- [ ] `tests/components/test_decorators.py` -- ALL occurrences of `._task_type` -> `.task_type`:
  - Line 39: `MyTask._task_type` -> `MyTask.task_type`
  - Line 61: `MyMLTask._task_type` -> `MyMLTask.task_type`
  - Line 73: `BigMLTask._task_type` -> `BigMLTask.task_type`
  - Line 89: `BaseComponent._task_type` -> `BaseComponent.task_type`
  - Lines 98-101: all `._task_type` -> `.task_type`
  - Lines 111, 114: `"_task_type" in cls.__dict__` -> `"task_type" in cls.__dict__`
  - Lines 121, 122: `._task_type` -> `.task_type`
  - Lines 129, 130: `._task_type` -> `.task_type`

- [ ] `tests/components/test_decorators.py` line 89 -- `BaseComponent._task_type == TaskType.ML_TASK` is wrong. BaseComponent declares `task_type: ClassVar[TaskType] = TaskType.TASK` (line 50 of base.py). Fix expectation to `TaskType.TASK`.

**Verification:**
```bash
uv run -- pytest tests/components/test_decorators.py -m unit -v
```

### 4.2 DeployModel field renames (9 failures)

**Problem:** `test_deploy.py` uses `endpoint_name=` (removed), `model_uri=`, `serving_container_image=` which no longer exist on DeployModel.

**Files:**
- [ ] `tests/components/test_deploy.py` -- rewrite all tests for new field names:
  - `TestDeployModelInstantiation`: Change `endpoint_name="churn-v1"` -> `model_name="churn-v1"`, remove assertions on `model_uri`, `serving_container_image`
  - `TestDeployModelExecute.test_deploy_model_execute_delegates`: Remove `model_uri=`, `serving_container_image=` from constructor and assertion. Update `mock_run_deploy.assert_called_once_with()` to match current `run_deploy()` signature
  - `TestDeployModelLifecycle`: Change `endpoint_name=` -> `model_name=`
  - `TestDeployModelMonitoring`: Change `endpoint_name=` -> `model_name=`

**Verification:**
```bash
uv run -- pytest tests/components/test_deploy.py -m unit -v
```

### 4.3 Vertex utils old signature (9 failures)

**Problem:** `test_vertex.py` uses `_COMMON_KWARGS` with `serving_container_image=` and passes `model_uri=` to `run_deploy()`. The current `run_deploy()` signature does NOT have these params.

**Files:**
- [ ] `tests/utils/test_vertex.py` -- rewrite entirely for new `run_deploy()` signature:
  - `_COMMON_KWARGS`: remove `serving_container_image`, remove `model_uri` from all calls
  - `TestSmartModelResolution`: Replace with tests for display-name lookup
  - `TestRunDeployCPR`: **Delete this entire class** (CPR kwargs no longer in `run_deploy()`)
  - `TestRunDeployMonitoring`: Update calls to remove `model_uri=`

**Verification:**
```bash
uv run -- pytest tests/utils/test_vertex.py -m unit -v
```

### 4.4 Config multi-env fields (9 failures)

**Problem:** `test_config.py` uses `dev_project_id`, `staging_project_id`, `prod_project_id`, `test_project_id` -- all removed. GCPConfig now has a single `project_id`.

**Files:**
- [ ] `tests/config/test_config.py` -- rewrite for single `project_id` model:
  - `TestEnvironmentEnum.test_environment_default_is_dev`: Use `GCPConfig(project_id="proj-dev")`
  - `TestEnvironmentEnum.test_environment_from_env_var`: Use `project_id=` instead of `staging_project_id=`. Change env vars from `GML_*` to unprefixed (`TEAM`, `PROJECT`, `BRANCH`, `ENVIRONMENT`)
  - `TestFrameworkConfigValidation`: Remove tests that validate per-env project IDs
  - `TestActiveGCPProject`: Rewrite tests to use `project_id=`
  - `TestMiscConfig`: Fix env vars and GCPConfig fields
  - All `GML_TEAM` -> `TEAM`, `GML_PROJECT` -> `PROJECT`, `GML_BRANCH` -> `BRANCH`

- [ ] `tests/config/test_context.py` -- fix helper `_make_context()`:
  - Line 48: `GCPConfig(prod_project_id="prod-proj")` -> `GCPConfig(project_id="prod-proj")`
  - Lines 55-58: All `GCPConfig(dev_project_id=...)`, `GCPConfig(test_project_id=...)`, `GCPConfig(staging_project_id=...)` -> `GCPConfig(project_id=...)`
  - Line 102: `GCPConfig(dev_project_id="dummy")` -> `GCPConfig(project_id="dummy")`
  - Lines 103-107: `GML_TEAM` -> `TEAM`, `GML_PROJECT` -> `PROJECT`, `GML_BRANCH` -> `BRANCH`

**Verification:**
```bash
uv run -- pytest tests/config/ -m unit -v
```

### 4.5 RegisterModel CPR tests (2 failures)

**Problem:** `test_register.py` `TestRegisterModelCPR` tests expect CPR kwargs in `Model.upload()` calls. Current `register.py` does NOT add CPR kwargs.

**Files:**
- [ ] `tests/components/test_register.py`:
  - `TestRegisterModelExecute.test_register_model_execute_calls_upload` lines 107-109: Remove assertions for `serving_container_predict_route` and `serving_container_health_route`
  - `TestRegisterModelCPR` class: **Delete entirely** -- CPR route injection was removed from RegisterModel

**Verification:**
```bash
uv run -- pytest tests/components/test_register.py -m unit -v
```

### 4.6 TrainModel lifecycle tests (4 failures)

**Problem:** Tests reference `self._work_dir`, `self.hyperparameters`, `self.trainer_args` which do not exist on TrainModel.

**Files:**
- [ ] `tests/components/test_train.py` -- update tests to match current TrainModel API:
  - `TestTrainModelInstantiation.test_train_model_instantiation`: Remove assertions on `trainer_args` and `hyperparameters`
  - `TestTrainModelExecute.test_train_model_execute_creates_temp_dir`: Rewrite -- `_work_dir` doesn't exist
  - `TestTrainModelExperiments`: Dependent on Phase 1.2 (experiment tracking move to `execute()`)

**Verification:**
```bash
uv run -- pytest tests/components/test_train.py -m unit -v
```

### 4.7 Pipeline definition tests (8 failures)

**Problem:** `test_steps.py` (training) and `test_compile.py` (verification) import pipeline definitions that use `endpoint_name=` (fixed in Phase 1.6).

**Files:**
- [ ] `tests/training_pipeline/test_steps.py` -- should pass after Phase 1.6. Verify step counts/names.
- [ ] `tests/verification_pipeline/test_compile.py` -- should pass after Phase 1.6.

**Verification:**
```bash
uv run -- pytest tests/training_pipeline/ tests/verification_pipeline/ -m unit -v
```

### 4.8 Smart compiler tests (GCPConfig fields)

**Problem:** `test_smart_compiler.py` uses old field names and env var prefixes.

**Files:**
- [ ] `tests/pipeline/test_smart_compiler.py` line 279 -- `GCPConfig(staging_project_id="staging-project")` -> `GCPConfig(project_id="staging-project")`
- [ ] `tests/pipeline/test_smart_compiler.py` line 284 -- `"GML_ENVIRONMENT": "staging"` -> `"ENVIRONMENT": "staging"`

**Verification:**
```bash
uv run -- pytest tests/pipeline/test_smart_compiler.py -m unit -v
```

### 4.9 Compiler tests (3 errors)

**Problem:** `test_compiler.py` passes `serving_image=` kwarg (now `default_image=`) and uses removed `endpoint_name=`.

**Files:**
- [ ] `tests/pipeline/test_compiler.py`:
  - Lines 132, 147, 167: `serving_image=` -> `default_image=`
  - Line 143: `DeployModel(component_name="deploy_step", endpoint_name="ep")` -> `DeployModel(component_name="deploy_step")`
  - `TestBuildDerivedParamsServingImage.test_deploy_model_gets_serving_image`: **Delete or rewrite** -- DeployModel no longer gets `serving_container_image` in derived params
  - `TestBuildContextParamsKeys.test_build_context_params_keys`: Verify expected keys match current `_build_context_params()` return

**Verification:**
```bash
uv run -- pytest tests/pipeline/test_compiler.py -m unit -v
```

### 4.10 Base component test (`_INTERNAL_FIELDS` mismatch)

**Problem:** `test_base.py` `TestInternalFields.test_internal_fields_set` expects `_INTERNAL_FIELDS` to be exactly `{"component_name", "component_version", "timeout_seconds", "retry_count", "cache_enabled"}`. After Phase 1.5 removes `"gcp_config"`, update expected set.

**Files:**
- [ ] `tests/components/test_base.py` line 61-65 -- update expected set:
  ```python
  expected = {
      "component_name", "component_version",
      "timeout_seconds", "retry_count", "cache_enabled",
      "runtime_dockerfile", "serving_dockerfile", "model_name",
  }
  ```

**Verification:**
```bash
uv run -- pytest tests/components/test_base.py -m unit -v
```

### Phase 4 Definition of Done

- [ ] `uv run -- pytest tests/ -m unit -v` -- 0 failures, 0 errors
- [ ] Every test file runs clean

**Verification:**
```bash
uv run -- pytest tests/ -m unit -v
uv run -- pytest tests/ -m unit -v --tb=no -q | tail -5
```

---

## Phase 5: Config, Scaffolding & Defaults

**REQS:** 8.0 (Typer), 14.0 (standard variables), 15.0 (Environment)

### 5.1 Fix `cmd_init.py` .env template (Bug 11)

**Problem:** `gml init project` generates env vars (`GML_TEAM`, `GML_GCP__DEV_PROJECT_ID`, etc.) that the framework cannot read.

**Files:**
- [ ] `gcp_ml_framework/cli/cmd_init.py` -- update `_DOT_ENV` template:
  - `GML_TEAM={team}` -> `TEAM={team}`
  - `GML_PROJECT={project}` -> `PROJECT={project}`
  - `GML_ENVIRONMENT=dev` -> `ENVIRONMENT=dev`
  - `GML_GCP__DEV_PROJECT_ID={dev_project}` -> `GCP_PROJECT_ID={dev_project}`
  - `GML_GCP__STAGING_PROJECT_ID={staging_project}` -> delete line
  - `GML_GCP__PROD_PROJECT_ID={prod_project}` -> delete line
  - `GML_GCP__REGION=us-east4` -> `GCP_REGION=us-east4`
  - Remove Composer env vars that use `GML_GCP__` prefix
- [ ] `gcp_ml_framework/cli/cmd_init.py` -- update `init_project()` function:
  - Remove `staging_project` and `prod_project` parameters
  - Remove associated lines
  - Update `_DOT_ENV.format()` call
- [ ] `gcp_ml_framework/cli/cmd_init.py` -- update `_PIPELINE_PY` template line 57:
  - `DeployModel(endpoint_name="{name}-endpoint")` -> `DeployModel(model_name="{name}")`
- [ ] `gcp_ml_framework/cli/cmd_init.py` -- update CI workflow templates:
  - `_CI_DEV_YAML`: `GML_GCP__DEV_PROJECT_ID` -> `GCP_PROJECT_ID`, `GML_TEAM` -> `TEAM`, `GML_PROJECT` -> `PROJECT`
  - `_CI_STAGE_YAML`: same pattern
  - `_PROMOTE_YAML`: same pattern

### 5.2 Clean `.env.example`

**Problem:** `.env.example` contains derived vars that should not be manually configured.

**Files:**
- [ ] `.env.example` -- clean up:
  - Remove `GCP_AR_HOST` line (derived from region)
  - Remove `GCP_AR_REPO` line (derived from team+project)
  - Remove stale `GML_GCP__*` comments at bottom
  - Keep: `TEAM`, `PROJECT`, `ENVIRONMENT`, `BRANCH`, `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_COMPOSER_DAGS_PATH`, `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL`

### 5.3 Fix `cache_enabled` default (Bug 8)

**Problem:** `base.py:57` has `cache_enabled: bool = True` but should default to `False` per the 2026-03-06 caching fix. Cached steps return URIs to deleted BQ tables after teardown.

**Files:**
- [ ] `gcp_ml_framework/components/base.py` line 57 -- `cache_enabled: bool = True` -> `cache_enabled: bool = False`

**Verification:**
```bash
uv run -- python -c "
from gcp_ml_framework.components.base import BaseComponent
# Verify default is False
import inspect
src = inspect.getsource(BaseComponent)
assert 'cache_enabled: bool = False' in src or 'cache_enabled: bool = Field(default=False' in src
print('OK')
"
```

### 5.4 Fix `enable_caching` default in runner (Bug 9)

**Problem:** `runner.py:29` has `enable_caching: bool = True` but should default to `False` to match the `RunPipelineJobOperator` setting in generated DAGs.

**Files:**
- [ ] `gcp_ml_framework/pipeline/runner.py` line 29 -- `enable_caching: bool = True` -> `enable_caching: bool = False`

**Verification:**
```bash
uv run -- python -c "
from gcp_ml_framework.pipeline.runner import VertexRunner
print('OK')
"
```

### Phase 5 Definition of Done

- [ ] `uv run -- gml init project testteam testproj --dev-project my-dev-proj --out /tmp/test_scaffold` generates correct .env
- [ ] Generated .env contains `TEAM=`, `PROJECT=`, `ENVIRONMENT=`, `GCP_PROJECT_ID=` (not `GML_*` prefixes)
- [ ] `.env.example` does not contain `GCP_AR_HOST` or `GCP_AR_REPO`
- [ ] Pipeline template uses `model_name=` not `endpoint_name=`
- [ ] `cache_enabled` defaults to `False` in `base.py`
- [ ] `enable_caching` defaults to `False` in `runner.py`

**Verification:**
```bash
grep "cache_enabled" gcp_ml_framework/components/base.py
grep "enable_caching" gcp_ml_framework/pipeline/runner.py
grep "GML_" .env.example
# Expected: no GML_ prefixes in .env.example
```

---

## Phase 6: Pydantic Migration & Code Cleanup

**REQS:** 7.0 (Pydantic), 3.0 (clean DAGs)

### 6.1 Convert `smart_compiler.py` @dataclass -> Pydantic (Bug 16)

**Problem:** `CompilationResult` and `_StepGroup` in `smart_compiler.py` use `@dataclass` (lines 25, 33). All other framework classes use Pydantic.

**Files:**
- [ ] `gcp_ml_framework/pipeline/smart_compiler.py`:
  - `from dataclasses import dataclass, field` -> `from pydantic import BaseModel, Field`
  - `@dataclass class CompilationResult:` -> `class CompilationResult(BaseModel):`
  - `yaml_paths: list[Path] = field(default_factory=list)` -> `yaml_paths: list[Path] = Field(default_factory=list)`
  - `@dataclass class _StepGroup:` -> `class _StepGroup(BaseModel):`
  - Add `model_config = {"arbitrary_types_allowed": True}` to `_StepGroup` (it holds `list[PipelineStep]` which contains `BaseComponent`)

**Verification:**
```bash
grep -r "@dataclass" gcp_ml_framework/
# Expected: no output
uv run -- pytest tests/pipeline/test_smart_compiler.py -m unit -v
```

### 6.2 Fix dead code removal -- move experiment tracking (dependent on Phase 1.2)

**Problem:** After Phase 1.2 removes dead code from `train.py:run()`, the experiment tracking code needs to be properly integrated into `execute()`.

**Files:**
- [ ] `gcp_ml_framework/components/ml/train.py` -- verify experiment tracking is in `execute()` after GCS upload:
  - `aiplatform.log_params()` call with component fields
  - `aiplatform.log_metrics()` call if metrics are available
  - All wrapped in `try/except` for best-effort logging

**Verification:**
```bash
uv run -- pytest tests/components/test_train.py -m unit -v
```

### 6.3 Add `__main__` block to `email.py` (Bug 13)

**Problem:** `email.py` is missing the `if __name__ == "__main__": Email.cli()` block that other components have.

**Files:**
- [ ] `gcp_ml_framework/components/operators/email.py` -- add at end of file:
  ```python
  if __name__ == "__main__":
      Email.cli()
  ```

**Verification:**
```bash
uv run -- python -c "
import ast
with open('gcp_ml_framework/components/operators/email.py') as f:
    tree = ast.parse(f.read())
has_main = any(
    isinstance(node, ast.If) and
    isinstance(node.test, ast.Compare) and
    any(isinstance(c, ast.Constant) and c.value == '__main__' for c in node.test.comparators)
    for node in ast.walk(tree)
)
assert has_main, 'Missing __main__ block'
print('OK')
"
```

### 6.4 Fix `cmd_deploy.py` logging inconsistency (Bug 14)

**Problem:** `cmd_deploy.py` uses `import logging` instead of loguru, inconsistent with the 12 other files using loguru.

**Files:**
- [ ] `gcp_ml_framework/cli/cmd_deploy.py` -- replace `import logging` with `from loguru import logger`, update all `logging.info()` / `logging.warning()` / `logging.error()` calls to `logger.info()` / `logger.warning()` / `logger.error()`

**Verification:**
```bash
grep "import logging" gcp_ml_framework/cli/cmd_deploy.py
# Expected: no output
```

### 6.5 Fix `context.py` field declaration order (Bug 19)

**Problem:** `pipeline_service_account_email: str = ""` is declared at line 96, after `@property` methods, in a `frozen=True` model. Valid Pydantic but breaks reading expectations.

**Files:**
- [ ] `gcp_ml_framework/context.py` -- move `pipeline_service_account_email` field declaration up to join the other field declarations (before line 44)

### 6.6 Fix WriteFeatures `render_operator()`

**Problem:** `write_features.py` `render_operator()` generates `PythonOperator(python_callable=_write_features_X)` but never defines the function in the generated DAG code.

**Files:**
- [ ] `gcp_ml_framework/components/feature_store/write_features.py` -- update `render_operator()` to generate both the function definition and the operator reference

**Verification:**
```bash
uv run -- python -c "
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
wf = WriteFeatures(entity='user', feature_group='churn')
code, imports = wf.render_operator(context=None)
print(code)
"
```

### 6.7 Regenerate DAGs and compiled pipelines (REQS 3.0)

- [ ] Delete stale files in `dags/` and `compiled_pipelines/`
- [ ] Run `UV_ENV_FILE=.env uv run -- gml compile --all`

**Verification:**
```bash
ls dags/ compiled_pipelines/
```

### Phase 6 Definition of Done

- [ ] `grep -r "@dataclass" gcp_ml_framework/` returns nothing
- [ ] `grep "import logging" gcp_ml_framework/cli/cmd_deploy.py` returns nothing
- [ ] `email.py` has `__main__` block
- [ ] `UV_ENV_FILE=.env uv run -- gml compile --all` succeeds
- [ ] Generated DAGs are valid Python (`python -c "compile(open('dags/X.py').read(), 'X', 'exec')"`)

**Verification:**
```bash
grep -r "@dataclass" gcp_ml_framework/
grep "import logging" gcp_ml_framework/cli/cmd_deploy.py
uv run -- ruff check gcp_ml_framework/
```

---

## Phase 7: Docker Cleanup, Cloud Build & Build Script

**REQS:** 4.0 (Docker tag), 18.0 (Cloud Build), 18.0b (Docker hierarchy simplification)
**Client design law (PR #26 `docs/deploy.md`):** Root-level defaults removed. Two Dockerfiles per pipeline: `base.Dockerfile` + `serve.Dockerfile` only. `base-python` as foundation.

### 7.1 Remove legacy/root-level Dockerfiles per client's PR #26 design (Bug 15)

**Problem:** Client's `docs/deploy.md` (PR #26) explicitly states: "Root-level default Dockerfiles (`docker/train.Dockerfile`, `docker/serve.Dockerfile`) were removed." But they still exist.

**Files to DELETE:**
- [ ] `docker/train.Dockerfile` -- root-level default, superseded by per-pipeline `base.Dockerfile`
- [ ] `docker/serve.Dockerfile` -- root-level default, superseded by per-pipeline `serve.Dockerfile`
- [ ] `docker/pipeline/Dockerfile` -- legacy unified image, no longer needed
- [ ] `docker/serving/Dockerfile` -- legacy serving image, no longer needed
- [ ] `docker/pipelines/house_price/train.Dockerfile` -- client target: only `base.Dockerfile` + `serve.Dockerfile` per pipeline

**Files to KEEP:**
- `docker/base/base-python/Dockerfile` -- foundation (Tier 0)
- `docker/pipelines/house_price/base.Dockerfile` -- per-pipeline execution image
- `docker/pipelines/house_price/serve.Dockerfile` -- per-pipeline serving image

### 7.2 Update `cloudbuild.yaml` (Bug 12)

**Problem:** `cloudbuild.yaml` references legacy Dockerfiles (`docker/pipeline/Dockerfile` and `docker/serving/Dockerfile`) that should be removed.

**Files:**
- [ ] `cloudbuild.yaml` -- update build steps to use per-pipeline Dockerfiles:
  - Remove steps referencing `docker/pipeline/Dockerfile`
  - Remove steps referencing `docker/serving/Dockerfile`
  - Add steps for `docker/pipelines/{pipeline}/base.Dockerfile`
  - Add steps for `docker/pipelines/{pipeline}/serve.Dockerfile`

**Verification:**
```bash
grep -n "docker/pipeline/" cloudbuild.yaml
grep -n "docker/serving/" cloudbuild.yaml
# Expected: no output
```

### 7.3 Update `scripts/docker_build.sh`

**Problem:** Build script may reference root-level default Dockerfiles and root-level build steps.

**Files:**
- [ ] `scripts/docker_build.sh` -- remove root-level default build steps; build only `base-python` + per-pipeline images
- [ ] Verify `NamingConvention.docker_image_name()` still works for pipeline-only images (no root-level)
- [ ] Verify image resolution in `gcp_ml_framework/pipeline/compiler.py` doesn't fall back to removed root-level defaults

**Verification:**
```bash
bash scripts/docker_build.sh --help  # or dry-run
```

### 7.4 Fix `sync=False` doc-code discrepancy in RegisterModel (Bug 7)

**Problem:** PR #26 removed `sync=False` from `register.py` `Model.upload()` but docs document it with rationale.

**Files:**
- [ ] `gcp_ml_framework/components/ml/register.py` -- re-add `sync=False` to `upload_kwargs` dict (line ~125)

**Verification:**
```bash
grep "sync" gcp_ml_framework/components/ml/register.py
# Expected: sync=False present
```

### 7.5 Ensure `{branch}-{sha}` tag is always used (REQS 4.0)

**Problem:** Docker build script may use `latest` tag for `main` branch instead of `{branch}-{sha}`.

**Files:**
- [ ] Read `scripts/docker_build.sh` -- verify tag logic
- [ ] If `main` branch gets `latest` tag, change to `{branch}-{sha}` everywhere
- [ ] Verify `NamingConvention.image_tag()` always returns `{branch}-{sha}`

### Phase 7 Definition of Done

- [ ] Legacy/root-level Dockerfiles removed: `docker/train.Dockerfile`, `docker/serve.Dockerfile`, `docker/pipeline/`, `docker/serving/`, `docker/pipelines/house_price/train.Dockerfile`
- [ ] Only `base-python` + per-pipeline `base.Dockerfile` + `serve.Dockerfile` remain
- [ ] `sync=False` re-added to `RegisterModel.run()` per client docs
- [ ] Docker tags always use `{branch}-{sha}` format
- [ ] `cloudbuild.yaml` does not reference legacy Dockerfiles
- [ ] Build script updated for simplified hierarchy

**Verification:**
```bash
# Only these Docker files should exist:
find docker/ -name "Dockerfile*" -o -name "*.Dockerfile" | sort
# Expected:
#   docker/base/base-python/Dockerfile
#   docker/pipelines/house_price/base.Dockerfile
#   docker/pipelines/house_price/serve.Dockerfile

# sync=False in RegisterModel
grep "sync" gcp_ml_framework/components/ml/register.py

# No legacy refs in cloudbuild.yaml
grep -n "docker/pipeline/" cloudbuild.yaml
grep -n "docker/serving/" cloudbuild.yaml

# Build script works with simplified hierarchy
bash scripts/docker_build.sh --help
```

---

## Phase 8: New Capabilities

**REQS:** 9.0, 10.0, 17.0, 18.0, 19.0, 20.0, 22.0

### 8.1 Structured Logging -- Loguru (REQS 9.0)

- [ ] Scan for remaining `print()` calls: `grep -rn "print(" gcp_ml_framework/ --include="*.py"`
- [ ] Replace with `logger.info()` / `logger.debug()` / `logger.warning()` as appropriate
- [ ] Add `from loguru import logger` where missing
- [ ] Exclude CLI output (typer/rich `console.print()`) from conversion -- those are intentional for UI

**Verification:**
```bash
grep -rn "print(" gcp_ml_framework/ --include="*.py" | grep -v "console.print" | grep -v "# noqa"
# Expected: no output (or only console.print calls)
```

### 8.2 Conditional/Loop Operators (REQS 22.0)

- [ ] Design doc: `docs/design_loop_condition.md`
  - DS API: `Pipeline.for_each(items, step)` and `Pipeline.condition(predicate, step)`
  - KFP mapping: `dsl.ParallelFor`, `dsl.Condition`
  - Airflow limitation: raise clear error if used with @task steps
- [ ] Implementation files: `builder.py`, `compiler.py`, `smart_compiler.py`
- [ ] Tests: `tests/pipeline/test_builder_loops.py`, `tests/pipeline/test_compiler_loops.py`

### 8.3 Mypy Enforcement (REQS 17.0)

- [ ] Add `[tool.mypy]` section to `pyproject.toml`
- [ ] Add `types-PyYAML` to dev dependencies
- [ ] Fix 20 type errors across 7 files (attr-defined, type mismatches, missing stubs)
- [ ] Target: `uv run -- mypy gcp_ml_framework/` -> 0 errors

**Verification:**
```bash
uv run -- mypy gcp_ml_framework/
```

### 8.4 DBT Integration (REQS 19.0)

- [ ] New component: `gcp_ml_framework/components/transformation/dbt_run.py`
  - `@task class DBTRun(BaseComponent)`
  - `render_operator()` -> `BashOperator` with `dbt run` command
  - Fields: `project_dir`, `target`, `models`, `vars`
- [ ] Export from `gcp_ml_framework/components/__init__.py`
- [ ] Tests: `tests/components/test_dbt_run.py`

### 8.5 Documentation (REQS 10.0, 20.0)

- [ ] Google-style docstrings on all public methods missing them (Email, compiler/builder public methods, `load_config()`)
- [ ] Create `AGENTS.md` at project root with architecture, components, pipelines, testing, configuration

### 8.6 Cloud Build IAM (REQS 18.0)

- [ ] Document IAM bindings needed for Cloud Build SA to access AR and GCS
- [ ] Verify Compute Engine SA has Cloud Build bucket access

### 8.7 GCP Best Practices Improvements

- ~~`gcp_ml_framework/naming.py:36-39`~~ -- already fixed in Phase 1.7
- [ ] `gcp_ml_framework/utils/ar.py` -- replace subprocess/gcloud CLI calls with `google-cloud-artifactregistry` SDK where feasible
- [ ] `gcp_ml_framework/components/operators/bq_query.py:129` -- fix unsafe SQL string escaping (parameterized queries or proper escaping)
- [ ] `gcp_ml_framework/components/operators/bq_query.py:146` -- make `gcp_conn_id` configurable instead of hardcoded `"google_cloud_default"`
- [ ] `gcp_ml_framework/secrets/client.py` -- add response caching for Secret Manager lookups
- [ ] All GCP SDK calls -- catch `google.api_core.exceptions.NotFound` instead of generic `Exception` where applicable

**Verification:**
```bash
grep -rn "except Exception" gcp_ml_framework/ --include="*.py"
# Expected: minimal/no generic exception catching
```

### Phase 8 Definition of Done

- [ ] No bare `print()` in framework code (excluding CLI)
- [ ] Loop/condition design doc exists with tests
- [ ] `uv run -- mypy gcp_ml_framework/` -> 0 errors
- [ ] `DBTRun` component with passing tests
- [ ] `AGENTS.md` exists at project root
- [ ] Cloud Build IAM documented
- [ ] Generic exception catching replaced with specific exceptions

**Verification:**
```bash
grep -rn "print(" gcp_ml_framework/ --include="*.py" | grep -v "console.print"
uv run -- mypy gcp_ml_framework/
test -f AGENTS.md
```

---

## Execution Order & Dependencies

```
Phase 1 (Critical Bugs)     -- no dependencies
Phase 2 (Ruff)              -- no dependencies, can parallel with Phase 1
Phase 3 (conftest)          -- depends on Phase 1 (pipeline definitions must import)
Phase 4 (Test Fixes)        -- depends on Phases 1, 2, 3
Phase 5 (Scaffolding)       -- depends on Phase 1
Phase 6 (Cleanup)           -- depends on Phase 4
Phase 7 (Docker/Build)      -- depends on Phase 1
Phase 8 (New Capabilities)  -- depends on Phases 1-7
```

**Recommended execution:** 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8

---

## Final Verification

```bash
# After all phases complete
uv run -- ruff check gcp_ml_framework tests
uv run -- pytest tests/ -m unit -v
UV_ENV_FILE=.env uv run -- gml compile --all
UV_ENV_FILE=.env uv run -- gml context show
grep -r "third_run" --include="*.py" --include="Dockerfile*" docker/ pipelines/
grep -r "@dataclass" gcp_ml_framework/
grep -r "endpoint_name=" pipelines/*/pipeline.py
grep "import logging" gcp_ml_framework/cli/cmd_deploy.py
grep -n "docker/pipeline/" cloudbuild.yaml
grep -n "docker/serving/" cloudbuild.yaml
find docker/ -name "Dockerfile*" -o -name "*.Dockerfile" | sort
# Phase 8 only:
uv run -- mypy gcp_ml_framework/
test -f AGENTS.md
```

---

## Not In Scope

| Item | REQS | Reason |
|------|------|--------|
| CI/CD pipeline setup | 16.0 | Explicitly deferred |
| Staging/Prod config | -- | DEV only |
| Terraform changes | -- | Infrastructure pre-existing |
| Multi-environment GCPConfig | -- | Single `project_id` is the current model |
