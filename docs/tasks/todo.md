# version_1 Development Roadmap

**Date:** 2026-03-20
**Status:** Phase 1 + Phase 2 + Phase 2.5 + Phase 3 + Phase 4 + Phase 4.5 + Phase 5 + Phase 5.5 COMPLETE — Phase 6 next
**Branch:** version_1
**Focus:** Dev environment, framework as package, TDD, real GCP validation
**Decisions:** See `docs/tasks/decisions.md` for architectural rationale (ADR-001 through ADR-011)
**USE UV FOR PYTHON and ENSURE RUFF HAS NO ERRORS WHEN EVER DEALING WITH PYTHON CODE**
---

## Overview

Transform version_1 from "right architecture, can't run" to a unified ML platform framework where data scientists define pipelines with `@task` and `@ml_task` decorators, the framework compiles to Airflow DAGs + Vertex AI pipelines automatically, and everything builds via Google Cloud Build.

**End state:** Data scientists write `pipeline.py` → `gml build` → `gml run --local` → `gml deploy`. They never touch KFP, Airflow, Docker, or Terraform.

**Not building yet:** PyPI publishing, cookiecutter templates, multi-env promotion, custom UIs.

---

## Dependency Graph & Parallelism

```
Phase 1: Critical Fixes + Test Foundation [DONE]
    │
    ├──→ Phase 2: Unified Task Architecture [DONE]
    │       │
    │       ├──→ Phase 4: Training Pipeline E2E [DONE]
    │       │       │
    │       │       └──→ Phase 4.5: Phases 1-4 Fixes [DONE]
    │       │               │
    │       │               └──→ Phase 5: Complete Pipeline + Experiments [DONE]
    │       │
    │       ├──→ Phase 6: Advanced Features [needs Phase 2, PARALLEL with 4/5]
    │       │
    │       └──→ Phase 7: DBT Integration [needs Phase 2, PARALLEL with 4/5/6]
    │
    ├──→ Phase 3: Cloud Build + Docker [DONE]
    │
    └──→ Phase 8: Polish [PARALLEL with everything after Phase 1]
```

**Execution tracks:**
- **Track A (critical path):** Phase 1 → Phase 2 → Phase 4 → **Phase 4.5** → Phase 5
- **Track B (parallel after Phase 1):** Phase 3 (Cloud Build)
- **Track C (parallel after Phase 2):** Phase 6, Phase 7
- **Track D (parallel after Phase 1):** Phase 8

---

## Phase 1: Critical Fixes + Test Foundation

**Why first:** Compiler crashes on import (`RegisterModel` missing). `ComponentConfig` creates boilerplate. `GitState` naming is wrong and coupled to git. No tests exist. Nothing else can proceed.

**ADRs:** ADR-002, ADR-003, ADR-004, ADR-009

---

### 1.1 Set Up Test Infrastructure

**What:** Create the test skeleton organized by functionality so TDD is possible from the start.

**Tasks:**
- [x] Create directory structure:
  ```
  tests/
  ├── __init__.py
  ├── conftest.py                 # Shared fixtures
  ├── config/
  │   ├── __init__.py
  │   ├── test_config.py          # FrameworkConfig, Environment, load_config
  │   ├── test_context.py         # MLContext, from_config, properties
  │   └── test_naming.py          # NamingConvention, slugify, all derived names
  ├── components/
  │   ├── __init__.py
  │   ├── test_base.py            # BaseComponent, cli(), execute(), run(), as_kfp_component()
  │   ├── test_train.py           # TrainModel lifecycle
  │   ├── test_evaluate.py        # EvaluateModel lifecycle
  │   ├── test_register.py        # RegisterModel (new)
  │   └── test_deploy.py          # DeployModel lifecycle
  ├── pipeline/
  │   ├── __init__.py
  │   ├── test_builder.py         # PipelineBuilder / Pipeline, step chaining, .build()
  │   ├── test_compiler.py        # PipelineCompiler, YAML output, cross-step wiring
  │   └── test_local_runner.py    # LocalRunner, in-process execution
  ├── cli/
  │   ├── __init__.py
  │   └── test_commands.py        # gml compile, gml run, gml context, gml build
  └── training_pipeline/
      ├── __init__.py
      ├── test_steps.py           # Step instantiation, run() behavior
      ├── test_integration.py     # Individual steps against real GCP (@pytest.mark.integration)
      └── test_e2e.py             # Full pipeline E2E (@pytest.mark.e2e)
  ```

- [x] Create `tests/conftest.py` with shared fixtures:
  ```python
  # Fixtures to create:
  # - mock_naming: NamingConvention(team="testteam", project="testproject", branch="testbranch")
  # - mock_gcp_config: GCPConfig(dev_project_id="test-project-id", region="us-central1")
  # - mock_framework_config: FrameworkConfig with minimal valid fields, branch="testbranch"
  #   NOTE: environment is now a direct field, not derived from branch
  # - mock_context: MLContext built from mock_framework_config
  # - tmp_pipeline_dir: tmp_path with minimal pipeline structure
  # - real_context: MLContext from real .env (for integration tests, skip if no .env)
  ```

- [x] Add tool configs to `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["."]
  markers = [
      "unit: Fast tests, no GCP credentials needed",
      "integration: Requires GCP credentials and dev project",
      "e2e: Full pipeline execution on GCP (slow)",
  ]
  addopts = "-v --tb=short"

  [tool.ruff]
  line-length = 100
  target-version = "py312"

  [tool.ruff.lint]
  select = ["E", "F", "I", "N", "W", "UP", "T201"]

  [tool.mypy]
  python_version = "3.12"
  warn_return_any = true
  warn_unused_configs = true
  ignore_missing_imports = true
  ```

- [x] Add `pytest` and `pytest-cov` to `[project.optional-dependencies.dev]`
- [x] Run `uv sync --extra dev` to install test dependencies
- [x] Verify: `uv run -- pytest tests/ -v` discovers 0 tests, exits 0

---

### 1.2 Create RegisterModel Component (REQS 21.0)

**What:** Compiler (`pipeline/compiler.py:13`) imports `RegisterModel` from a module that doesn't exist. Every `gml compile` call crashes. Also completes REQS 21.0 (Model Registry Step).

**TDD — tests first:**
- [x] Create `tests/components/test_register.py`:
  - `test_register_model_instantiation` — creates with default fields (model_uri, model_display_name, serving_container_image, labels, description)
  - `test_register_model_is_base_component` — isinstance check, has universal fields
  - `test_register_model_has_cli` — classmethod inherited from BaseComponent
  - `test_register_model_execute_calls_upload` — mock `google.cloud.aiplatform`, verify `Model.upload()` called with correct params
  - `test_register_model_writes_output_uri` — execute() writes `model.resource_name` to `output_uri_path` (use tmp_path)
  - `test_register_model_cli_entrypoint` — `if __name__` block exists

**Then implement:**
- [x] Create `gcp_ml_framework/components/ml/register.py`:
  - `class RegisterModel(BaseComponent)` with fields: `model_uri`, `model_display_name`, `serving_container_image`, `labels` (dict), `description`
  - `execute()`: calls `aiplatform.init()` → `Model.upload()` → writes resource_name to output_uri_path
  - `if __name__ == "__main__": RegisterModel.cli()`
- [x] Update `gcp_ml_framework/components/ml/__init__.py` to export RegisterModel

**Verify:**
- [x] `uv run -- pytest tests/components/test_register.py -v` — all pass
- [x] `uv run -- python -c "from gcp_ml_framework.pipeline.compiler import PipelineCompiler"` — no import error

---

### 1.3 Flatten ComponentConfig into BaseComponent (REQS 13.0)

**What:** Remove `ComponentConfig` as separate nested object. Move `machine_type`, `accelerator_type`, `accelerator_count`, `timeout_seconds`, `retry_count`, `cache_enabled` directly onto `BaseComponent`. Data scientists write `machine_type="n2-standard-8"` directly instead of `config=ComponentConfig(...)`.

**TDD — tests first:**
- [x] Create `tests/components/test_base.py`:
  - `test_base_component_has_flat_resource_fields` — `BaseComponent(machine_type="n2-standard-8").machine_type == "n2-standard-8"`
  - `test_component_config_class_removed` — `ComponentConfig` not importable
  - `test_resource_fields_are_internal` — machine_type, accelerator_type etc. in `_INTERNAL_FIELDS`
  - `test_cli_excludes_resource_fields` — cli() doesn't generate --machine-type flag
  - `test_as_kfp_component_excludes_resource_fields` — not KFP input params
  - `test_subclass_inherits_resource_fields` — TrainModel(machine_type="n2-standard-8") works

**Then implement:**
- [x] In `gcp_ml_framework/components/base.py`:
  - Move all `ComponentConfig` fields to `BaseComponent`
  - Remove `ComponentConfig` class entirely
  - Remove `config` field from `BaseComponent`
  - Add resource fields to `_INTERNAL_FIELDS`
- [x] Search codebase for `self.config.` and `ComponentConfig` — update all references:
  - `compiler.py`: any `step.component.config.machine_type` → `step.component.machine_type`
  - `pipelines/training_pipeline/pipeline.py`: remove `config=ComponentConfig(...)` if present
- [x] Verify no file imports `ComponentConfig`

**Verify:**
- [x] `uv run -- pytest tests/components/test_base.py -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/components/base.py` — passes
- [x] `grep -r "ComponentConfig" gcp_ml_framework/` — returns nothing

---

### 1.4 Environment Overhaul (REQS 15.0 + 16.0)

**What:** Three changes in one:
1. Rename `GitState` → `Environment` (REQS 15.0)
2. Add `LOCAL`, `TEST` values, rename `PROD_EXP` → `EXPERIMENT` (ADR-003)
3. Remove `_resolve_git_state()` — environment is a direct input via `GML_ENVIRONMENT` (ADR-002, REQS 16.0)

**Scope of changes (every file referencing GitState/git_state):**
- `gcp_ml_framework/config.py` — definition + resolution logic + FrameworkConfig property
- `gcp_ml_framework/context.py` — MLContext.git_state field + is_production()
- `gcp_ml_framework/pipeline/compiler.py` — _build_context_params()
- `gcp_ml_framework/dag/compiler.py` — schedule logic (DEV = no schedule)
- `gcp_ml_framework/cli/cmd_deploy.py`, `cmd_run.py`, `cmd_teardown.py` — may reference git_state
- `dags/*.py` — generated, will be regenerated

**TDD — tests first:**
- [x] Create `tests/config/test_config.py`:
  - `test_environment_enum_values` — LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT all exist as StrEnum
  - `test_environment_is_direct_field` — `FrameworkConfig(team="t", project="p", environment="staging", gcp=GCPConfig(staging_project_id="x")).environment == Environment.STAGING`
  - `test_environment_from_env_var` — set `GML_ENVIRONMENT=test` → FrameworkConfig resolves to TEST
  - `test_environment_default_is_dev` — when GML_ENVIRONMENT not set, defaults to "dev"
  - `test_no_resolve_git_state_function` — `_resolve_git_state` and `_resolve_environment` don't exist
  - `test_framework_config_validates_project_for_environment` — staging env requires staging_project_id, etc.
  - `test_load_config_from_yaml` — load_config() reads pipeline config.yaml, env vars override
  - `test_branch_is_independent_of_environment` — branch="feature/x" with environment="staging" is valid

**Then implement:**
- [x] In `config.py`:
  - Rename `class GitState` → `class Environment`
  - Values: `LOCAL = "local"`, `DEV = "dev"`, `TEST = "test"`, `STAGING = "staging"`, `PROD = "prod"`, `EXPERIMENT = "experiment"`
  - Delete `_resolve_git_state()` function entirely
  - Change `FrameworkConfig`:
    - Add `environment: str = "dev"` field (Pydantic Settings picks up `GML_ENVIRONMENT`)
    - Delete `git_state` property
    - Add `@property def resolved_environment(self) -> Environment: return Environment(self.environment)`
    - Update `_validate_projects` to use `Environment(self.environment)` instead of `_resolve_git_state(self.branch)`
    - Update `active_gcp_project` to use new environment field
  - Add `test_project_id: str = ""` to `GCPConfig` (for TEST environment)
- [x] In `context.py`:
  - Rename `git_state` field → `environment` (type: `Environment`)
  - Update `from_config()`: `environment=Environment(cfg.environment)`
  - Update `is_production()`: check `PROD` and `EXPERIMENT`
  - Update `summary()`: show `environment` not `git_state`
- [x] In `pipeline/compiler.py`:
  - `_build_context_params()`: `context.environment.value` instead of `context.git_state.value`
- [x] In `dag/compiler.py`:
  - Schedule logic: `Environment.DEV` instead of `GitState.DEV`
  - Import update
- [x] In CLI commands: update all references to git_state
- [x] Global verification: `grep -r "GitState\|git_state\|_resolve_git_state" gcp_ml_framework/` — returns nothing

**Verify:**
- [x] `uv run -- pytest tests/config/test_config.py -v` — all pass
- [x] `uv run -- gml context show` — shows `environment: dev`, correct namespace, GCP project *(verified with real .env in Phase 2.5)*
- [x] Zero references to `GitState` or `git_state` in framework code

---

### 1.5 Core Framework Tests

**What:** Lock down existing behavior of config, context, naming, builder, compiler, and DAG system with unit tests. These are the safety net for all future changes.

**Tasks:**
- [x] `tests/config/test_naming.py`:
  - NamingConvention construction, namespace, namespace_bq
  - gcs_bucket, gcs_path, gcs_pipeline_root, gcs_data_path, gcs_model_path
  - bq_table, bq_feature_table
  - vertex_pipeline_display_name, vertex_experiment, vertex_model_name, vertex_endpoint_name, vertex_training_job_name
  - artifact_registry_repo, image_uri, image_tag
  - feature_store_id, feature_view_id
  - dag_id, secret_name
  - _slugify edge cases (special chars, long strings, uppercase)
  - _bq_safe edge cases
  - get_git_branch (mock subprocess)

- [x] `tests/config/test_context.py`:
  - MLContext.from_config builds correctly
  - All properties: namespace, bq_dataset, gcs_prefix, feature_store_id, pipeline_service_account
  - is_production() True for PROD and EXPERIMENT, False for DEV/TEST/STAGING/LOCAL
  - summary() returns dict with all expected keys
  - MLContext is frozen (immutable)

- [x] `tests/pipeline/test_builder.py`:
  - PipelineBuilder chaining (.ingest().transform().train().build())
  - .build() returns PipelineDefinition with correct step count
  - .build() raises ValueError on empty pipeline
  - .step() creates step with stage="custom"
  - Named methods set correct stages
  - Step names default to "{stage}_{index}" if not specified
  - Custom step names preserved
  - PipelineDefinition.step_names returns name list

- [x] `tests/pipeline/test_compiler.py`:
  - Compiler imports without error (RegisterModel exists)
  - _build_context_params returns correct keys including environment
  - _build_derived_params computes job_name for TrainModel
  - _build_derived_params computes model_display_name for RegisterModel
  - _build_derived_params computes feature_view_id for WriteFeatures
  - compile() produces a .yaml file (mock KFP compiler)
  - Cross-step data flow wiring: train output → evaluate model_uri

- [x] ~~`tests/dag/test_builder.py`~~: *(skipped — DAGBuilder deleted in Phase 2.5)*

- [x] `tests/dag/test_compiler.py` *(deleted in Phase 2.5, coverage replaced in test_smart_compiler.py)*:
  - render() produces valid Python (exec() doesn't raise)
  - Generated DAG has zero gcp_ml_framework imports
  - DEV schedule is None, STAGING/PROD uses declared schedule
  - BQ task renders to BigQueryInsertJobOperator
  - Vertex pipeline task renders to RunPipelineJobOperator
  - Template variables resolved ({bq_dataset}, {gcs_prefix})

**Verify:**
- [x] `uv run -- pytest tests/ -m unit -v` — 78 passed
- [ ] `uv run -- pytest tests/ --cov=gcp_ml_framework --cov-report=term-missing` — review coverage *(nice-to-have, deferred to Phase 8)*

---

### 1.6 Create .env.example

- [x] Create `.env.example` with all `GML_*` vars, no real values, comments explaining each
- [x] Include `GML_ENVIRONMENT=dev` (new: environment is explicit input)
- [x] Include Docker build vars (`AR_HOST`, `GCP_PROJECT`, `AR_REPO`)
- [x] Include `GML_GCP__TEST_PROJECT_ID` for TEST environment

---

### Phase 1 Definition of Done

- [x] `uv run -- pytest tests/ -m unit -v` → all pass (78 tests)
- [x] `uv run -- ruff check tests/` → passes (framework pre-existing issues not in scope)
- [x] `uv run -- python -c "from gcp_ml_framework.pipeline.compiler import PipelineCompiler"` → no import error
- [x] `uv run -- gml compile training_pipeline` → produces valid KFP YAML (5356 bytes) + Airflow DAG (1819 bytes) *(verified with real .env in Phase 2.5)*
- [x] `RegisterModel` exists with full test suite
- [x] `ComponentConfig` class deleted, fields flat on BaseComponent
- [x] `GitState` → `Environment` everywhere, zero old references
- [x] Environment is direct input (GML_ENVIRONMENT), not derived from git
- [x] `.env.example` exists and is git-tracked
- [x] `pyproject.toml` has ruff, mypy, pytest config sections

---

## Phase 2: Unified Task Architecture

**Why:** Eliminate cognitive overload. Data scientists learn ONE system, not two. The framework makes infrastructure decisions (Airflow vs Vertex AI), not data scientists.

**ADRs:** ADR-001, ADR-008, ADR-009
**Depends on:** Phase 1

This is the largest phase — a fundamental architecture change touching ~20 files.

---

### 2.1 Design @task and @ml_task Decorators

**What:** Define the decorator API that determines execution target.

**TDD — tests first:**
- [x] Create `tests/components/test_decorators.py`:
  - `test_task_decorator_sets_task_type` — `@task class Foo(BQQuery)` → `Foo._task_type == TaskType.TASK`
  - `test_ml_task_decorator_sets_task_type` — `@ml_task class Bar(TrainModel)` → `Bar._task_type == TaskType.ML_TASK`
  - `test_ml_task_accepts_resource_params` — `@ml_task(machine_type="n2-standard-8")` sets machine_type on class
  - `test_task_decorator_preserves_class` — decorated class is still a proper Pydantic BaseModel
  - `test_default_task_types` — BQQuery defaults to TASK, TrainModel defaults to ML_TASK
  - `test_override_default_task_type` — `@ml_task class MyBQQuery(BQQuery)` overrides default to ML_TASK

**Then implement:**
- [x] Create `gcp_ml_framework/decorators.py`:
  ```python
  class TaskType(StrEnum):
      TASK = "task"           # Compiled to Airflow operator
      ML_TASK = "ml_task"     # Compiled to Vertex AI container component

  def task(cls):
      """Mark component as lightweight — compiles to Airflow operator."""
      cls._task_type = TaskType.TASK
      return cls

  def ml_task(_cls=None, *, machine_type=None, accelerator_type=None, ...):
      """Mark component as ML compute — compiles to Vertex AI container."""
      def decorator(cls):
          cls._task_type = TaskType.ML_TASK
          if machine_type: cls._default_machine_type = machine_type
          ...
          return cls
      if _cls: return decorator(_cls)
      return decorator
  ```
- [x] Add `_task_type` field to `BaseComponent` (default based on subclass)
- [x] Set default `_task_type` on built-in components:
  - `@task`: BQQuery, BQTransform, WriteFeatures, ReadFeatures, Email, DbtRun
  - `@ml_task`: TrainModel, EvaluateModel, RegisterModel, DeployModel

---

### 2.2 Unify BaseTask into BaseComponent

**What:** Merge the DAG task system into the component system. `BQQueryTask` → `BQQuery(BaseComponent)`. `EmailTask` → `Email(BaseComponent)`.

**TDD — tests first:**
- [x] Extend `tests/components/test_base.py`:
  - `test_bq_query_component` — BQQuery has sql, sql_file, destination_table fields
  - `test_bq_query_execute` — execute() runs real BQ query (mock for unit test)
  - `test_bq_query_render_operator` — render_operator() returns BigQueryInsertJobOperator code
  - `test_email_component` — Email has to, subject, body fields
  - `test_email_render_operator` — render_operator() returns EmailOperator code
  - `test_task_type_component_has_render_operator` — TASK types have render_operator()
  - `test_ml_task_component_has_as_kfp_component` — ML_TASK types have as_kfp_component()

**Then implement:**
- [x] Add `render_operator(self, context) -> str` method to `BaseComponent`:
  - For `@task` components: returns Airflow operator Python code string
  - For `@ml_task` components: raises NotImplementedError (they use as_kfp_component)
- [x] Create unified components from DAG tasks:
  - `BQQuery` (merges `BigQueryExtract` + `BQQueryTask`):
    - Fields: sql, sql_file, destination_table, write_disposition
    - `execute()`: runs query via Python SDK (for local execution)
    - `render_operator()`: returns BigQueryInsertJobOperator code (for Airflow compilation)
    - `_resolve_sql()`: template variable resolution ({bq_dataset}, {gcs_prefix}, {run_date})
  - `Email` (from `EmailTask`):
    - Fields: to, subject, body, cc
    - `execute()`: sends email via SMTP or logs warning locally
    - `render_operator()`: returns EmailOperator code
  - Keep `BQTransform` as-is (already a component, add render_operator for Airflow path)
- [x] Update `gcp_ml_framework/components/__init__.py` to export all unified components

---

### 2.3 Create Unified Pipeline Builder

**What:** Replace `PipelineBuilder` + `DAGBuilder` with a single `Pipeline` builder.

**TDD — tests first:**
- [x] Create `tests/pipeline/test_unified_builder.py`:
  - `test_pipeline_add_with_stage_inference` — `.add(BQQuery(...))` infers stage="ingest"
  - `test_pipeline_add_ml_task` — `.add(TrainModel(...))` infers stage="train"
  - `test_pipeline_mixed_task_types` — `.add(BQQuery()).add(TrainModel()).add(Email())` works
  - `test_pipeline_build` — produces PipelineDefinition with correct steps and task types
  - `test_pipeline_chaining` — fluent API returns self
  - `test_pipeline_empty_raises` — .build() on empty raises ValueError
  - `test_pipeline_step_names` — custom names preserved, defaults generated
  - `test_backward_compat_methods` — .ingest(), .train() etc. still work

**Then implement:**
- [x] Rename `PipelineBuilder` → `Pipeline` in `pipeline/builder.py`
  - Keep `PipelineBuilder` as alias for backward compatibility
  - `.add()` method replaces `.step()` as primary API
  - `.add()` calls `_infer_stage()` from component type
  - Stage inference map: BQQuery→ingest, BQTransform→transform, TrainModel→train, etc.
  - Named methods (.ingest(), .train() etc.) remain as aliases
- [x] Update `PipelineStep` model:
  - Add `task_type: TaskType` field (from component._task_type)
- [x] Update `PipelineDefinition`:
  - Property `ml_task_groups` → returns groups of consecutive ML_TASK steps (for Vertex AI pipeline compilation)
  - Property `has_mixed_types` → True if both @task and @ml_task steps exist
- [x] Create `gcp_ml_framework/__init__.py` exports: `Pipeline`, `task`, `ml_task`

---

### 2.4 Build Smart Compiler

**What:** The compiler that auto-splits mixed pipelines into Airflow DAG + Vertex AI pipeline(s).

**TDD — tests first:**
- [x] Create `tests/pipeline/test_smart_compiler.py`:
  - `test_all_ml_tasks_compiles_to_vertex_only` — pure @ml_task pipeline → KFP YAML + thin DAG wrapper
  - `test_all_tasks_compiles_to_dag_only` — pure @task pipeline → Airflow DAG only, no YAML
  - `test_mixed_pipeline_splits_correctly` — @task,@task,@ml_task,@ml_task,@task → DAG with 2 BQ operators + RunPipelineJobOperator + 1 operator
  - `test_ml_task_grouping` — consecutive @ml_task steps grouped into one Vertex AI pipeline
  - `test_split_ml_groups` — @ml_task,@task,@ml_task → two separate Vertex AI pipelines
  - `test_data_flow_task_to_ml` — BQ table reference passed as parameter to Vertex AI pipeline
  - `test_data_flow_ml_to_task` — Vertex AI output available in subsequent @task step
  - `test_compiled_dag_has_zero_framework_imports` — generated DAG code has no gcp_ml_framework imports

**Then implement:**
- [x] Create `gcp_ml_framework/pipeline/smart_compiler.py`:
  ```
  class SmartCompiler:
      def compile(pipeline_def, context) -> CompilationResult:
          # 1. Group steps by task_type boundaries
          groups = self._group_steps(pipeline_def.steps)
          # 2. For each ML_TASK group: compile to KFP YAML via PipelineCompiler
          # 3. Generate Airflow DAG that orchestrates:
          #    - @task steps as native Airflow operators (via render_operator)
          #    - ML_TASK groups as RunPipelineJobOperator (references compiled YAML)
          # 4. Wire data flow between groups

      def _group_steps(steps) -> list[StepGroup]:
          # Split into groups at task_type boundaries
          # [TASK, TASK, ML_TASK, ML_TASK, TASK] →
          #   [TaskGroup(TASK,TASK), MlGroup(ML_TASK,ML_TASK), TaskGroup(TASK)]

      def _compile_ml_group(group, context) -> Path:
          # Reuse existing PipelineCompiler for the ML steps
          # Returns path to compiled KFP YAML

      def _render_dag(groups, context, yaml_paths) -> str:
          # Generate Airflow DAG code
          # @task groups → Airflow operators
          # ML groups → RunPipelineJobOperator referencing YAML
  ```
- [x] Update `gml compile` command to use SmartCompiler
- [x] Keep existing `PipelineCompiler` for internal use (compiles ML step groups to KFP YAML)
- [x] Keep existing `DAGCompiler` for internal use (generates Airflow operator code)

---

### 2.5 Update LocalRunner for Unified Model

**What:** `gml run --local` must handle both @task and @ml_task steps, executing all in-process.

**TDD — tests first:**
- [x] Create `tests/pipeline/test_local_runner.py`:
  - `test_local_runner_executes_task_steps` — calls execute() on @task components
  - `test_local_runner_executes_ml_task_steps` — calls execute() on @ml_task components
  - `test_local_runner_threads_output` — output_uri from step N passed to step N+1
  - `test_local_runner_mixed_pipeline` — handles @task and @ml_task in sequence
  - `test_local_runner_injects_context` — context params merged into each component

**Then implement:**
- [x] Create `gcp_ml_framework/pipeline/local_runner.py`:
  - `LocalRunner.run(pipeline_def, context, run_date="")`:
    - For each step regardless of task_type: instantiate component with merged params, call execute()
    - Thread output_uri between steps (same logic as compiler)
    - TrainModel output → last_model_output; others → last_dataset_output
- [x] Update `gcp_ml_framework/cli/cmd_run.py`:
  - Add `--local` flag
  - When `--local`: load pipeline, build context, call LocalRunner

---

### 2.6 Migrate training_pipeline to New API

**What:** Update the existing pipeline to use the unified `Pipeline` builder with `@task`/`@ml_task`.

**Tasks:**
- [x] Update `pipelines/training_pipeline/pipeline.py`:
  ```python
  from gcp_ml_framework import Pipeline, ml_task
  from gcp_ml_framework.components import TrainModel
  from pipelines.training_pipeline.steps.train_house_model import TrainHouseModel

  pipeline = (
      Pipeline(name="training_pipeline", schedule="@daily")
      .add(TrainHouseModel(machine_type="n2-standard-4"), name="Train House Price Model")
      .build()
  )
  ```
- [x] Verify `gml compile training_pipeline` produces valid YAML + DAG file

---

### Phase 2 Definition of Done

- [x] `@task` and `@ml_task` decorators work on all component types
- [x] `Pipeline` builder replaces `PipelineBuilder` + `DAGBuilder`
- [x] SmartCompiler splits mixed pipelines into Airflow DAG + Vertex AI YAML
- [x] `gml run --local` handles both task types
- [x] training_pipeline migrated to new API
- [x] All new tests pass: `uv run -- pytest tests/ -m unit -v` (128 tests pre-cleanup)
- [x] `gml compile training_pipeline` produces correct YAML + DAG

---

## Phase 2.5: Deprecation Cleanup

**Why:** Old DAG system deprecated in Phase 2, fully deleted here since nothing is in production and zero dag.py pipelines exist. Also includes config simplification (framework.yaml removal) and code quality fixes.

**Depends on:** Phase 2

---

### 2.5.1 Delete Old DAG System

- [x] Deleted entire `gcp_ml_framework/dag/` directory (11 files: builder, compiler, factory, operators, runner, tasks/*)
- [x] Deleted `tests/dag/` directory (2 files: __init__.py, test_compiler.py — 4 tests)
- [x] Removed `_compile_dag()`, `_compile_embedded_vertex_pipelines()`, `_load_dag()` from cmd_compile.py
- [x] Removed dag.py detection from cmd_deploy.py (`_resolve_match_names` simplified)
- [x] Removed `--composer` flag and `_run_composer()` from cmd_run.py
- [x] Removed `--dag` flag and DAG templates (`_DAG_PY`, `_DAG_CONFIG_YAML`, `_DAG_EXTRACT_SQL`, `_DAG_TRANSFORM_SQL`) from cmd_init.py
- [x] Updated `_PIPELINE_PY` template to use `Pipeline.add()` API instead of old `PipelineBuilder.ingest()` chain

### 2.5.2 Code Quality Fixes

- [x] Fixed 4 Pydantic deprecation warnings (`instance.model_fields` → `type(instance).model_fields`)
- [x] Fixed all ruff errors in Phase 1+2 files (E501, I001, UP032)
- [x] Added 3 replacement tests to test_smart_compiler.py (valid python, dev schedule, non-dev schedule)
- [x] Net test count: 128 → 127 (-4 old DAG tests + 3 new SmartCompiler tests)

### 2.5.3 Config Simplification (Drop framework.yaml)

- [x] Added `GML_TEAM` + `GML_PROJECT` to `.env` — single source of truth for all config
- [x] Deleted `_find_framework_yaml()` from config.py, removed `framework_yaml` param from `load_config()`
- [x] Removed `framework_yaml` param from `_helpers.py:load_context()`
- [x] Removed `--config`/`-c` CLI flag from all 5 commands (context, compile, deploy, run, teardown)
- [x] Updated `cmd_init.py` to scaffold `.env` instead of `framework.yaml`
- [x] Updated `bootstrap.sh` to read env vars instead of grepping YAML
- [x] Updated `.env.example` — `GML_TEAM`/`GML_PROJECT` promoted to required
- [x] Deleted `framework.yaml`
- [x] Updated all docs (CLAUDE.md, decisions.md, discussion.md, todo.md, phases_done.md, seed_bq.sh)

### Phase 2.5 Definition of Done

- [x] Old DAG system fully deleted — zero references to DAGBuilder, BaseTask, ComposerRunner
- [x] Zero Pydantic deprecation warnings
- [x] Zero ruff errors across entire codebase
- [x] `framework.yaml` deleted — zero references in Python code
- [x] All config via env vars (`.env`) — `gml context show` works without framework.yaml
- [x] All tests pass: `uv run -- pytest tests/ -m unit -v` (127 tests)

---

## Phase 3: Cloud Build + Docker

**Why:** Eliminate Docker Desktop from developer machines. Shared layer cache across team. Faster builds on Cloud Build machines. Same build process everywhere.

**ADRs:** ADR-005, ADR-011
**REQS:** 18.0, 18.0b
**Parallel with:** Phase 2

---

### 3.1 Create cloudbuild.yaml

**Tasks:**
- [x] Create `cloudbuild.yaml`:
  ```yaml
  # Multi-step build with AR layer caching
  # Step 1: Build base-python (cached, changes rarely)
  # Step 2: Build {pipeline-name} image (cached deps layer + fresh source layer)
  # Substitutions: _TAG (branch-sha), _REPO, _PIPELINE
  # Machine: E2_HIGHCPU_8
  # Cache: --cache-from pulls cached layers from AR
  ```
- [x] Create `.gcloudignore`:
  - Exclude: `.terraform/`, `*.tfstate*`, `*.tfvars`, `.env`, `.env.*`, `*.pem`, `*.key`, `*credentials*`, `*secret*`, `.claude/`, `REQS.docx`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `node_modules/`

---

### 3.2 Simplify Docker Image Hierarchy (REQS 18.0b)

**What:** Merge `component-base` and `base-ml` into a single pipeline image.

**Tasks:**
- [x] Keep `docker/base/base-python/Dockerfile` (Python 3.12 + uv — cached layer)
- [x] Create `docker/pipeline/Dockerfile` (merged from base-ml, installs ALL extras):
  ```dockerfile
  ARG BASE_IMAGE=base-python:latest
  FROM ${BASE_IMAGE}
  # Layer 1 (cached): Install all dependencies
  COPY pyproject.toml uv.lock ./
  RUN uv sync --frozen --extra components --extra trainer --no-install-project
  # Layer 2 (changes often): Source code
  COPY gcp_ml_framework/ gcp_ml_framework/
  COPY second_run/ second_run/
  COPY pipelines/ pipelines/
  COPY pyproject.toml ./
  RUN uv sync --frozen --extra components --extra trainer
  ```
- [x] Delete `docker/base/component-base/Dockerfile`
- [x] Delete `docker/base/base-ml/Dockerfile`

---

### 3.3 Implement `gml build` CLI Command

**TDD — tests first:**
- [x] `tests/cli/test_commands.py`:
  - `test_build_command_exists` — `gml build --help` works
  - `test_build_constructs_correct_gcloud_command` — verify substitutions, tag, config path

**Then implement:**
- [x] Create `gcp_ml_framework/cli/cmd_build.py`:
  - `gml build [pipeline_name | --all]`
  - Derives image tag from branch + git SHA (same logic as `docker_build.sh`)
  - Calls `gcloud builds submit --config cloudbuild.yaml --substitutions _TAG=...,_PIPELINE=...,_REPO=...`
  - Returns full image URI
  - Supports `--timeout` flag (default 1200s)
- [x] Register in `cli/main.py`
- [x] Update `cli/cmd_deploy.py`: `_ensure_images()` uses `gml build` instead of `docker_build.sh`

---

### 3.4 Terraform IAM for Cloud Build

**Tasks:**
- [x] ~~Terraform IAM for Cloud Build~~ — **Deferred.** Sandbox uses pre-existing SAs; worked around with `--service-account` flag in Phase 4
- [x] Verify: `gcloud builds submit` works with correct permissions *(verified in Phase 4 — both pipelines build successfully)*

---

### Phase 3 Definition of Done

- [x] `uv run -- gml build training_pipeline` → image built on Cloud Build, pushed to AR *(verified in Phase 4)*
- [x] Docker Desktop NOT required on developer machine
- [x] Shared layer cache works: second build from different machine is <60s *(verified in Phase 4)*
- [x] Docker hierarchy: 2 layers (base-python → pipeline image)
- [x] `component-base` and `base-ml` Dockerfiles deleted
- [x] `.gcloudignore` excludes all sensitive files
- [x] ~~Terraform IAM~~ — Deferred (sandbox pre-existing SAs; worked around with `--service-account` flag in Phase 4)

---

## Phase 3.5: Rename Service Account Config for Clarity

**Why:** The current `GML_GCP__SERVICE_ACCOUNT_EMAIL` is ambiguous — the project has 3 SAs but the config doesn't say which one this is. It's the Vertex AI Pipeline SA. Renaming to `PIPELINE_SERVICE_ACCOUNT_EMAIL` aligns with Terraform outputs (which already use `pipeline_service_account_email` and `composer_service_account_email`) and prevents confusion as the project matures.

**Scope:** Rename only. No new SAs added to framework config.

---

### SA Architecture (3 SAs total, 1 in framework config)

| SA | Identity (sandbox) | Used by | In `.env`? | Why / Why not |
|---|---|---|---|---|
| **Pipeline SA** | `<pipeline-sa-name>@<project>.iam.gserviceaccount.com` | `runner.py` (Vertex job submission), `smart_compiler.py` (DAG generation) | **YES → rename** | Framework passes this SA to `job.submit()` and `RunPipelineJobOperator`. Must be configurable. |
| **Composer SA** | `<composer-sa-name>@<project>.iam.gserviceaccount.com` | Airflow runtime (runs DAGs), Terraform IAM (impersonation) | **NO** | Framework uploads DAGs to GCS bucket — uses caller's gcloud auth, not Composer SA. Impersonation (Composer→Pipeline) is a Terraform IAM binding, not a framework concern. |
| **Cloud Build SA** | `{project_number}@cloudbuild.gserviceaccount.com` | `gcloud builds submit` (automatic) | **NO** | Auto-created, auto-used. `gml build` delegates to `gcloud` which handles auth implicitly. |

### Tasks

- [x] Rename in `gcp_ml_framework/config.py:43`: `service_account_email` → `pipeline_service_account_email`
- [x] Rename in `gcp_ml_framework/context.py:39,70,107,108`: all references to the field
- [x] Rename in `.env.example:26`: `GML_GCP__SERVICE_ACCOUNT_EMAIL` → `GML_GCP__PIPELINE_SERVICE_ACCOUNT_EMAIL`
- [x] Rename in `.env`: same (user's actual config file)
- [x] Add explanatory comments to `.env.example` documenting all 3 SAs and why only Pipeline SA is configured
- [x] Verify: `uv run -- pytest tests/ -m unit -v` — 132 passed
- [x] Verify: `uv run -- ruff check gcp_ml_framework/ tests/` — All checks passed
- [x] Verify: `UV_ENV_FILE=.env uv run -- gml context show` — correct

### What does NOT change

- **Composer SA** — not added to `.env`. The framework doesn't need it. Composer runs DAGs as itself; the DAGs tell Vertex to use the Pipeline SA. Impersonation is IAM.
- **Cloud Build SA** — not added to `.env`. `gcloud builds submit` uses it implicitly. No framework code references it.
- **Terraform modules** — already use `pipeline_service_account_email` and `composer_service_account_email` (no change needed)
- **Tests** — `conftest.py` doesn't set this field; `test_context_pipeline_service_account` tests the derived value which still works
- **Generated DAGs** — regenerated on next `gml compile`, will pick up the change automatically

---

## Phase 4: Training Pipeline E2E on GCP

**Why:** Prove the unified architecture works end-to-end. Framework that can't run a pipeline is useless.

**Depends on:** Phase 2 (unified system) + Phase 3 (Docker images)

---

### 4.1 Configure Dev Environment

- [x] Verify `.env` has correct dev project ID, region, SA email, Composer details
- [x] Verify `GML_ENVIRONMENT=dev` is set in `.env`
- [x] Run `uv run -- gml context show` — all fields correct
- [x] Run `./scripts/bootstrap.sh` to ensure APIs enabled (idempotent)
- [x] Verify Terraform: `cd terraform/envs/dev && terraform init && terraform plan`
- [x] If needed: `terraform apply` (confirm with user)

### 4.2 Seed BigQuery Data

- [x] Run: `UV_ENV_FILE=.env uv run -- sh -c './scripts/seed_bq.sh'`
- [x] Verify: `bq query "SELECT COUNT(*) FROM $DATASET.housing_data_table"` returns rows

### 4.3 Run Train Step Locally Against GCP

- [x] Run train step directly via CLI
- [x] Verify: Model pickle uploaded to GCS

### 4.4 Test gml run --local

- [x] Run: `UV_ENV_FILE=.env uv run -- gml run training_pipeline --local`
- [x] Verify: Pipeline executes in-process, model in GCS

### 4.5 Compile Pipeline

- [x] Run: `UV_ENV_FILE=.env uv run -- gml compile training_pipeline`
- [x] Verify: YAML + DAG file produced, correct image URIs, no inlined Python

### 4.6 Build Docker Image via Cloud Build

- [x] Run: `UV_ENV_FILE=.env uv run -- gml build training_pipeline`
- [x] Verify: Image in Artifact Registry with correct tag

### 4.7 Deploy to GCP

- [x] Run: `UV_ENV_FILE=.env uv run -- gml deploy training_pipeline`
- [x] Verify: DAG uploaded to Composer, YAML uploaded to GCS

### 4.8 Remove --vertex Flag, Add Composer Trigger

**Why:** `--vertex` bypasses Composer and submits directly to Vertex AI. This contradicts
the architecture where Composer is the sole orchestrator (SmartCompiler generates DAGs with
`RunPipelineJobOperator`). Mixed pipelines with `@task` steps would silently skip those steps.
The architecture docs (discussion.md) never mention `--vertex` — data scientists use `--local`
for dev and `gml deploy` + Composer for GCP execution.

- [x] Remove `--vertex` flag, `--sync`, `--no-cache` from `cmd_run.py`
- [x] Remove `_run_vertex()` function from `cmd_run.py`
- [x] `gml run pipeline` (default) → triggers deployed DAG in Composer via `gcloud composer environments run`
- [x] `gml run pipeline --local` → stays as-is
- [x] Update tests in `tests/cli/test_commands.py` (10 new tests)
- [x] `VertexRunner` class stays (internal utility, not user-facing)

### 4.9 Trigger Pipeline via Composer (E2E)

- [x] Run: `UV_ENV_FILE=.env uv run -- gml run training_pipeline`
- [x] DAG triggered successfully: `mlplatform_second_run_version___training_pipeline` (state: running)
- [x] Verify: DAG triggers → RunPipelineJobOperator submits to Vertex AI → pipeline completes *(both pipelines triggered and running on Composer)*

### 4.10 Write E2E Tests

- [x] `tests/training_pipeline/test_e2e.py`:
  - `test_compile_produces_yaml` (@pytest.mark.e2e)
  - `test_local_run_completes` (@pytest.mark.e2e)
- [x] `tests/training_pipeline/test_steps.py`:
  - `test_step_cli_help` (@pytest.mark.unit — every step responds to --help)

---

### Phase 4 Definition of Done

- [x] BQ data seeded
- [x] Single step runs locally against real GCP
- [x] `gml run --local` completes full pipeline
- [x] `gml compile` → valid YAML + DAG
- [x] `gml build` → image in AR via Cloud Build
- [x] `gml deploy` → DAG + YAML in GCP
- [x] `--vertex` flag removed, `gml run` triggers via Composer
- [x] `gml run training_pipeline` → Composer DAG triggered (running)
- [x] E2E tests written (unit: 146 passing, e2e: 2 tests)

---

## Phase 4.5: Phases 1-4 Fixes ✅ COMPLETE

**Status:** All 10 sub-tasks completed. 174 tests passing, ruff clean, both pipelines compile.

**Why:** Audit revealed the unified architecture is partially implemented. ML components lack `@ml_task` decorators (relying on BaseComponent default). The `execute() → run()` lifecycle — the core data-scientist contract — is broken on all ML components except TrainModel. Four `@task` components silently become no-ops in compiled Airflow DAGs because they lack `render_operator()`. ReadFeatures is an empty shell. The training_pipeline is 1 step, not 5 — proving only the happy path. This phase fixes all structural gaps so Phase 5 builds on a solid foundation.

**Depends on:** Phase 4
**Blocks:** Phase 5

---

### Summary of Issues Found

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | TrainModel, EvaluateModel, RegisterModel, DeployModel have no `@ml_task` decorator | Work by accident (BaseComponent defaults to ML_TASK), but violates the decorator architecture | Add explicit `@ml_task` to each |
| 2 | `execute()` bypasses `run()` on EvaluateModel, RegisterModel, DeployModel | Data scientists who subclass and override `run()` get `NotImplementedError` — their code never executes | Refactor: move current `execute()` body into `run()`, make `execute()` call `self.run()` |
| 3 | BQTransform has no `render_operator()` | Becomes `lambda: None` (no-op) in compiled Airflow DAGs; Phase 2.2 explicitly planned this | Add `render_operator()` → `BigQueryInsertJobOperator` |
| 4 | SmartCompiler fallback is `lambda: None` (line 328) | @task components without `render_operator()` silently do nothing in production DAGs | Replace with clear error: require `render_operator()` on @task components in compiled DAGs |
| 5 | ReadFeatures has no `execute()`, no `run()`, orphaned utility | Raises `NotImplementedError` at runtime — completely broken | Remove class + orphaned `run_read_features()` utility |
| 6 | BigQueryExtract is redundant with BQQuery | Phase 2.2 planned "BQQuery (merges BigQueryExtract + BQQueryTask)" — never done. No `render_operator()`, not used in any pipeline | Delete component + `run_bigquery_extract()` utility |
| 7 | GCSExtract has no `render_operator()`, unused | Not used in any pipeline, no functional tests, would be no-op in compiled DAGs | Delete component + `run_gcs_extract()` utility; re-add with `render_operator()` when needed |
| 8 | `PipelineBuilder` with 8 named stage methods still exists (REQS 11.0 says delete) | Data scientists see `.ingest()`, `.train()` etc. and think stages/order matter. They don't — SmartCompiler ignores `stage` entirely. 10 ways to add a step when there should be 1. | Delete `PipelineBuilder`, named methods, `stage` field, `_STAGE_MAP_BY_NAME`. Keep only `Pipeline.add()` |
| 9 | `stage` field on `PipelineStep` is dead code | Set on every step, consumed by nothing. SmartCompiler routes on `task_type`, compiler routes on `isinstance()`. Stage implies hierarchy that doesn't exist. | Remove `stage` from `PipelineStep`, remove `_infer_stage()` |
| 10 | No multi-step mixed pipeline exists to prove architecture | training_pipeline has 1 step (TrainModel) — only tests the happy path | Create `verification_pipeline` with @task + @ml_task steps |
| 11 | Email.render_operator() signature mismatch | SmartCompiler passes `pipeline_dir=` kwarg but Email.render_operator() doesn't accept it — will crash at runtime | Add `**kwargs` or `pipeline_dir` param to Email.render_operator() |
| 12 | WriteFeatures has no `render_operator()` | After 4.5.4 makes SmartCompiler raise NotImplementedError, WriteFeatures becomes unusable in compiled pipelines | Add `render_operator()` — metadata-only, renders as PythonOperator or custom operator |
| 13 | `utils/sql_compat.py` is dead DuckDB code | Completely orphaned — nothing imports it. Contradicts "no DuckDB" policy | Delete file |
| 14 | `utils/logging.py` is dead stdlib logging | Completely orphaned — loguru used everywhere. Nothing imports it | Delete file |
| 15 | `PipelineDefinition.ml_task_groups` never called | Dead property — duplicates SmartCompiler._group_steps() logic | Delete property |
| 16 | `components/__init__.py` has no re-exports | discussion.md envisions `from gcp_ml_framework.components import BQQuery, TrainModel` — currently requires 3-level deep imports | Add import facade |
| 17 | `cmd_deploy.py` swallows compilation errors | `except SystemExit: pass` on line 58 — deploy continues after compile failure | Fix error handling |
| 18 | `cmd_init.py` scaffolds non-existent CLI commands | References `gml promote`, `gml deploy dags`, `gml run --compile-only` — none exist | Fix scaffolded CI templates |
| 19 | Duplicated `_load_pipeline()` in cmd_compile.py + cmd_run.py | Identical function copy-pasted in two CLI modules | Extract to shared helper |

---

### 4.5.1 Add Explicit `@ml_task` Decorators to ML Components

**What:** The 4 ML components rely on `BaseComponent._task_type = TaskType.ML_TASK` (the default on `base.py:50`). This works by accident but contradicts the decorator architecture. The `@task` side is correct — all 6 `@task` components have explicit decorators. The `@ml_task` side was missed.

**Files to change (1-line per file):**

- [x] `gcp_ml_framework/components/ml/train.py` — add `@ml_task` decorator + import
- [x] `gcp_ml_framework/components/ml/evaluate.py` — add `@ml_task` decorator + import
- [x] `gcp_ml_framework/components/ml/register.py` — add `@ml_task` decorator + import
- [x] `gcp_ml_framework/components/ml/deploy.py` — add `@ml_task` decorator + import

**Tests to update:**
- [x] `tests/components/test_decorators.py` — verified ML components have explicit `@ml_task`

**Verify:**
- [x] `uv run -- pytest tests/components/test_decorators.py -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/components/ml/` — clean

---

### 4.5.2 Fix `execute()` → `run()` Lifecycle on ML Components

**What:** The architecture promises: "data scientists subclass a component and override `run()`. The component's `execute()` wraps `run()` with I/O lifecycle." Only `TrainModel` follows this — its `execute()` creates a temp dir, calls `self.run()`, then uploads to GCS. The other 3 ML components override `execute()` directly and never call `run()`. A data scientist who subclasses `EvaluateModel` and overrides `run()` gets `NotImplementedError` because `execute()` goes straight to a utility function.

**The fix:** Move each component's current `execute()` body into `run()`. Make `execute()` the lifecycle wrapper that calls `self.run()`. Default `run()` does what `execute()` used to do. Data scientists override `run()` to customize.

**TrainModel** — already correct (no changes needed):
```python
# execute() creates temp dir → calls self.run() → uploads to GCS ✅
```

**EvaluateModel** (`gcp_ml_framework/components/ml/evaluate.py`):

- [x] Move current `execute()` body into `run()` *(done)*

**RegisterModel** (`gcp_ml_framework/components/ml/register.py`):

- [x] Move current `execute()` body into `run()`, keep output_uri_path writing in `execute()` *(done)*

**DeployModel** (`gcp_ml_framework/components/ml/deploy.py`):

- [x] Move current `execute()` body into `run()`:
  ```python
  def execute(self) -> None:
      """Container lifecycle: call run()."""
      self.run()

  def run(self) -> None:
      """Deploy model to Vertex AI Endpoint. Override for custom deployment logic."""
      from gcp_ml_framework.utils.vertex import run_deploy

      run_deploy(
          project=self.project,
          region=self.region,
          model_uri=self.model_uri,
          model_display_name=self.model_display_name,
          endpoint_display_name=self.endpoint_display_name,
          serving_container_image=self.serving_container_image,
          machine_type=self.machine_type,
          min_replica_count=self.min_replica_count,
          max_replica_count=self.max_replica_count,
          traffic_split=self.traffic_split,
          output_uri_path=self.output_uri_path,
      )
  ```

**Note on @task components:** BQQuery, Email, BigQueryExtract, GCSExtract, BQTransform, WriteFeatures — NOT changing. These are framework-provided components used as-is (not subclassed by data scientists). Their `execute()` directly doing work is correct for their use case. The `run()` override pattern is for ML components where custom business logic is expected.

**Tests:**
- [x] `tests/components/test_evaluate.py` — execute_calls_run, subclass_run_override
- [x] `tests/components/test_register.py` — execute_calls_run, run_returns_resource_name, execute_writes_output_uri
- [x] `tests/components/test_deploy.py` — execute_calls_run, subclass_run_override

**Verify:**
- [x] `uv run -- pytest tests/components/ -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/components/ml/` — clean

---

### 4.5.3 Fix `render_operator()` Across All @task Components

**What:** Phase 2.2 (todo.md line 417) explicitly planned: "Keep BQTransform as-is (already a component, add render_operator for Airflow path)". This was never done. BQTransform is a `@task` component that runs SQL transformations — it should render as a `BigQueryInsertJobOperator` in compiled Airflow DAGs, exactly like BQQuery does.

**File:** `gcp_ml_framework/components/transformation/bq_transform.py`

- [x] Add `render_operator()` method → BigQueryInsertJobOperator *(done)*
- [x] Add TYPE_CHECKING import for MLContext

**Tests:**
- [x] `tests/components/test_bq_transform.py` — render_operator exists, returns BQ operator, resolves templates, includes destination

**3b. Fix Email.render_operator() signature mismatch (runtime crash)**

**What:** SmartCompiler._render_task_step() (line 318) calls `component.render_operator(context, pipeline_dir=pipeline_dir)`. But Email.render_operator() only accepts `(self, context: MLContext)` — no `pipeline_dir` kwarg. This means compiling ANY pipeline containing Email will crash with `TypeError: render_operator() got an unexpected keyword argument 'pipeline_dir'`.

**File:** `gcp_ml_framework/components/operators/email.py`

- [x] Add `pipeline_dir` kwarg to match SmartCompiler's call signature *(done)*
- [x] Add `from pathlib import Path` to TYPE_CHECKING imports

**3c. Add render_operator() to WriteFeatures**

**What:** WriteFeatures is `@task` but has no `render_operator()`. After 4.5.4 makes SmartCompiler raise NotImplementedError for missing render_operator(), WriteFeatures becomes unusable in compiled pipelines. WriteFeatures is a metadata-only operation (registers a BQ table as a Feature Store FeatureGroup) — render as a PythonOperator that calls the Vertex AI Feature Store API.

**File:** `gcp_ml_framework/components/feature_store/write_features.py`

- [x] Add `render_operator()` → PythonOperator *(done)*

**Tests:**
- [x] `tests/components/test_email.py` — render_operator accepts pipeline_dir
- [x] `tests/components/test_write_features.py` — render_operator exists, returns PythonOperator

**Verify:**
- [x] `uv run -- pytest tests/components/test_bq_transform.py tests/components/test_email.py -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/components/ -v` — clean

---

### 4.5.4 Fix SmartCompiler No-Op Fallback

**What:** `smart_compiler.py:324-329` has a `lambda: None` fallback for @task components without `render_operator()`. This silently makes components do nothing in production DAGs. Replace with a clear error so developers know they need to implement `render_operator()`.

**File:** `gcp_ml_framework/pipeline/smart_compiler.py`

- [x] Replaced lambda: None fallback with NotImplementedError *(done)*

**Tests:**
- [x] `tests/pipeline/test_smart_compiler.py` — test_task_without_render_operator_raises

**Verify:**
- [x] `uv run -- pytest tests/pipeline/test_smart_compiler.py -v` — all pass

---

### 4.5.5 Remove Redundant & Broken Components

**What:** Three components and their utilities need removal:

| Component | Problem | Rationale |
|-----------|---------|-----------|
| **ReadFeatures** | No `execute()`, no `run()`, broken at runtime | Empty shell — `run_read_features()` utility exists but is orphaned (never called). Re-add when Feature Store reads are actually needed. |
| **BigQueryExtract** | Redundant with BQQuery, no `render_operator()` | Phase 2.2 explicitly planned: "BQQuery (merges BigQueryExtract + BQQueryTask)". BQQuery already has `render_operator()`, `execute()`, `resolve_sql()` — it's the complete version. BigQueryExtract is the leftover that should have been deleted. Not used in any pipeline. |
| **GCSExtract** | No `render_operator()`, not used in any pipeline | Would be a silent no-op in compiled DAGs. No pipeline references it. No functional tests. Can be re-added with proper `render_operator()` when a pipeline actually needs GCS-to-GCS copy. |

**Complete file deletion list:**

- [x] Delete `gcp_ml_framework/components/ingestion/bigquery_extract.py` *(done)*
- [x] Delete `gcp_ml_framework/components/ingestion/gcs_extract.py` *(done)*
- [x] Delete `gcp_ml_framework/utils/bigquery_extract.py` *(done)*
- [x] Delete `gcp_ml_framework/utils/sql_compat.py` *(done)*
- [x] Delete `gcp_ml_framework/utils/logging.py` *(done)*
- [x] Delete `gcp_ml_framework/utils/gcs_extract.py` *(done)*

**Files to edit:**

- [x] `gcp_ml_framework/components/feature_store/write_features.py` — ReadFeatures deleted, WriteFeatures kept
- [x] `gcp_ml_framework/utils/feature_store.py` — orphaned `run_read_features()` deleted
- [x] `gcp_ml_framework/pipeline/builder.py` — stage map entries and read_features() method deleted
  - Delete `PipelineDefinition.ml_task_groups` property *(done)*

- [x] `tests/components/test_decorators.py` — removed deleted component imports/assertions
- [x] `tests/pipeline/test_builder.py` — deleted (replaced by test_unified_builder.py)
- [x] `gcp_ml_framework/components/ingestion/__init__.py` — cleaned

**What stays (NOT removing):**

| Component | Why keep |
|-----------|----------|
| **BQQuery** | Has `render_operator()`, `execute()`, `resolve_sql()` — complete @task component |
| **BQTransform** | Getting `render_operator()` in 4.5.3 — actively needed for verification_pipeline |
| **Email** | Has `render_operator()`, complete @task component |
| **WriteFeatures** | Has `execute()`, actively referenced by compiler + local_runner for metadata-only handling |

**Verify:**
- [x] `uv run -- pytest tests/ -m unit -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/ tests/` — clean
- [x] Zero references to removed components

---

### 4.5.6 Collapse Pipeline API (REQS 11.0)

**What:** REQS 11.0 says: "Collapse specialized methods into a single step() method to clarify that a pipeline is simply an ordered sequence of steps, and any component type can be used at any position." We kept all 8 named methods and `PipelineBuilder` as a parent class "for backward compatibility" — but there's nothing to be backward-compatible WITH. The old `DAGBuilder` consumers were deleted in Phase 2.5. Zero pipelines use `.ingest()` or `.train()`. Every pipeline (including discussion.md examples) uses `Pipeline.add()`.

The `stage` field on `PipelineStep` is dead code: set on every step, consumed by zero downstream systems. SmartCompiler groups on `task_type`. PipelineCompiler wires data on `isinstance()`. LocalRunner wires data on `isinstance()`. Generated DAGs and YAMLs never reference `stage`.

**What stays:** `Pipeline`, `PipelineStep`, `PipelineDefinition`, `.add()`, `.build()`
**What goes:** `PipelineBuilder`, all named methods, `stage`, `_STAGE_MAP_BY_NAME`, `_infer_stage()`

**File:** `gcp_ml_framework/pipeline/builder.py`

- [x] Remove `_STAGE_MAP_BY_NAME` dict
- [x] Remove `_infer_stage()` function
- [x] Remove `stage` field from `PipelineStep`
- [x] Delete `PipelineBuilder` class entirely
- [x] Make `Pipeline` a standalone class (not extending `PipelineBuilder`):
  ```python
  class Pipeline:
      """Unified pipeline builder. A pipeline is an ordered sequence of steps.

      Usage:
          pipeline = (
              Pipeline(name="training", schedule="@daily")
              .add(BQQuery(sql="SELECT ..."), name="Ingest")
              .add(TrainModel(), name="Train")
              .add(Email(to=["team@co.com"]), name="Notify")
              .build()
          )
      """

      def __init__(
          self,
          name: str,
          schedule: str | None = "@daily",
          description: str = "",
          tags: list[str] | None = None,
      ) -> None:
          self._name = name
          self._schedule = schedule
          self._description = description
          self._tags = tags or []
          self._steps: list[PipelineStep] = []

      def add(self, component: BaseComponent, name: str | None = None) -> Pipeline:
          """Add a component to the pipeline.

          The task_type is read from the component's _task_type ClassVar
          (set by @task or @ml_task decorator).
          """
          step_name = name or f"{type(component).__name__}_{len(self._steps)}"
          task_type = getattr(component, "_task_type", TaskType.ML_TASK)
          self._steps.append(
              PipelineStep(name=step_name, component=component, task_type=task_type)
          )
          return self

      def build(self) -> PipelineDefinition:
          if not self._steps:
              raise ValueError(
                  f"Pipeline '{self._name}' has no steps. "
                  "Add at least one step before calling .build()."
              )
          return PipelineDefinition(
              name=self._name,
              schedule=self._schedule,
              steps=list(self._steps),
              description=self._description,
              tags=self._tags,
          )
  ```
- [x] Update module docstring to remove PipelineBuilder examples and named method references

**Exports to update:**

- [x] `gcp_ml_framework/__init__.py` — PipelineBuilder removed
- [x] `gcp_ml_framework/pipeline/__init__.py` — Pipeline exported
- [x] `gcp_ml_framework/components/__init__.py` — import facade added:
  ```python
  from gcp_ml_framework.components.ml.train import TrainModel
  from gcp_ml_framework.components.ml.evaluate import EvaluateModel
  from gcp_ml_framework.components.ml.register import RegisterModel
  from gcp_ml_framework.components.ml.deploy import DeployModel
  from gcp_ml_framework.components.operators.bq_query import BQQuery
  from gcp_ml_framework.components.operators.email import Email
  from gcp_ml_framework.components.transformation.bq_transform import BQTransform
  from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
  ```
  This enables the discussion.md target: `from gcp_ml_framework.components import BQQuery, TrainModel`

**Tests to update:**

- [x] Delete `tests/pipeline/test_builder.py` — replaced by test_unified_builder.py
- [x] `tests/pipeline/test_unified_builder.py` — absorbed tests from test_builder.py
- [x] `tests/pipeline/test_compiler.py` — updated to use Pipeline.add()

**Verify:**
- [x] `uv run -- pytest tests/pipeline/ -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/pipeline/ tests/pipeline/` — clean
- [x] Zero grep hits for PipelineBuilder, _STAGE_MAP, _infer_stage, named methods

---

### 4.5.7 Create `verification_pipeline`

**What:** The current training_pipeline has 1 step (TrainModel). It only proves the @ml_task happy path. We need a mixed @task + @ml_task pipeline to prove the SmartCompiler actually works end-to-end. This pipeline is intentionally simple — its purpose is architectural verification, not ML sophistication.

**Pipeline structure:**

```python
# pipelines/verification_pipeline/pipeline.py
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from pipelines.verification_pipeline.steps.train_verify_model import TrainVerifyModelStep

pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    .add(
        BQQuery(
            sql="SELECT * FROM `{bq_dataset}.housing_data_table` WHERE 1=1",
            destination_table="verification_raw",
            component_name="ingest_raw",
        ),
        name="Ingest Raw Data",
    )
    .add(
        BQTransform(
            sql="SELECT *, CURRENT_TIMESTAMP() AS processed_at FROM `{bq_dataset}.verification_raw`",
            output_table="verification_features",
            component_name="transform_features",
        ),
        name="Transform Features",
    )
    .add(
        TrainVerifyModelStep(
            component_name="train_verify_model",
            machine_type="n2-standard-4",
        ),
        name="Train Model",
    )
    .build()
)
```

**What this proves:**
- `Pipeline.add()` with mixed @task (BQQuery, BQTransform) + @ml_task (TrainModel subclass)
- SmartCompiler groups: `[TASK(BQQuery), TASK(BQTransform)] → DAG operators` + `[ML_TASK(Train)] → KFP YAML`
- BQQuery.render_operator() → BigQueryInsertJobOperator
- BQTransform.render_operator() → BigQueryInsertJobOperator (new from 4.5.3)
- TrainModel subclass → KFP container component
- Compiled DAG has BQ operators + RunPipelineJobOperator

**Files to create:**

- [x] `pipelines/verification_pipeline/__init__.py` — empty
- [x] `pipelines/verification_pipeline/pipeline.py` — created
- [x] `pipelines/verification_pipeline/steps/__init__.py` — empty
- [x] `pipelines/verification_pipeline/steps/train_verify_model.py`:
  ```python
  """Simple training step for verification — trains on verification_features table."""
  import pickle
  from pathlib import Path

  from loguru import logger
  from gcp_ml_framework.components.ml.train import TrainModel


  class TrainVerifyModelStep(TrainModel):
      """Minimal training step for architecture verification."""

      def run(self) -> None:
          from google.cloud import bigquery
          from second_run.estimator import HousePredictionModel

          logger.info(f"[train_verify_model] project={self.project}, dataset={self.dataset}")
          client = bigquery.Client(project=self.project)
          query = f"SELECT * FROM `{self.dataset}.verification_features`"
          df = client.query(query).to_dataframe()

          model = HousePredictionModel()
          model.fit(df, df["price"])

          local_path = Path(self._work_dir) / "model.pkl"
          with open(local_path, "wb") as f:
              pickle.dump(model, f)
          logger.info(f"[train_verify_model] Model saved to {local_path}")
  ```

- [x] `pipelines/verification_pipeline/sql/` — NOT needed (SQL is inline for simplicity)

**Verify compilation:**
- [x] `UV_ENV_FILE=.env uv run -- gml compile verification_pipeline` *(done)*
- [x] Check compiled YAML: contains container component for train step
- [x] Check compiled DAG: BigQueryInsertJobOperator x2 + RunPipelineJobOperator with sequential deps

---

### 4.5.8 Tests for Verification Pipeline

**Tests to create:**

- [x] `tests/verification_pipeline/__init__.py` — created
- [x] `tests/verification_pipeline/test_compile.py` — 10 tests (definition + compilation)

**Verify:**
- [x] `uv run -- pytest tests/verification_pipeline/ -v` — all pass
- [x] `uv run -- pytest tests/ -m unit -v` — 176 tests total

---

### 4.5.9 Fix CLI Bugs

**What:** Several CLI issues that should be fixed while we're cleaning up the architecture.

**9a. cmd_deploy.py swallows compilation errors**

**File:** `gcp_ml_framework/cli/cmd_deploy.py`

The deploy command catches `SystemExit` from `compile_cmd` and silently continues:
```python
except SystemExit:
    pass  # compile_cmd uses typer.Exit for flow control
```
If compilation fails, deploy should NOT continue deploying broken artifacts.

- [x] Fix error handling — checks `e.code != 0` *(done)*

**9b. cmd_init.py scaffolds non-existent CLI commands**
- [x] Fix scaffolded CI to use real CLI commands (`gml compile --all`, `gml deploy --all`)
- [x] Fix `.python-version` from `3.11` to `3.12`

**9c. Extract duplicated `_load_pipeline()`**
- [x] Create `gcp_ml_framework/cli/_helpers.py` with shared function
- [x] Update both `cmd_compile.py` and `cmd_run.py` to import from `_helpers`

**Verify:**
- [x] `uv run -- pytest tests/cli/ -v` — all pass
- [x] `uv run -- ruff check gcp_ml_framework/cli/` — clean

---

### 4.5.10 Full Verification

- [x] `uv run -- pytest tests/ -m unit -v` — 176 tests (166 passed, 8 skipped needing .env, 2 e2e deselected)
- [x] `uv run -- ruff check gcp_ml_framework/ tests/` — zero errors
- [x] `UV_ENV_FILE=.env uv run -- gml compile --all` — compiles both pipelines
- [x] `UV_ENV_FILE=.env uv run -- gml compile verification_pipeline` — produces YAML with BQ + Vertex operators
- [x] Inspect generated DAG: confirmed 2 BigQueryInsertJobOperators + 1 RunPipelineJobOperator
- [x] `UV_ENV_FILE=.env uv run -- gml run verification_pipeline --local` — all 3 steps completed on real GCP
- [x] Zero grep hits for dead code

---

### Phase 4.5 Definition of Done ✅

- [x] All 4 ML components have explicit `@ml_task` decorators
- [x] `execute()` calls `run()` on all ML components (EvaluateModel, RegisterModel, DeployModel fixed; TrainModel already correct)
- [x] Data scientist subclass pattern works: override `run()` → custom code executes
- [x] All @task components have consistent `render_operator()`:
  - [x] BQTransform has `render_operator()` → `BigQueryInsertJobOperator`
  - [x] Email.render_operator() accepts `pipeline_dir` kwarg (signature matches SmartCompiler)
  - [x] WriteFeatures has `render_operator()` → `PythonOperator`
- [x] SmartCompiler raises `NotImplementedError` for @task components without `render_operator()` (no silent no-ops)
- [x] Redundant components and dead code removed:
  - [x] ReadFeatures deleted (broken shell, orphaned utility)
  - [x] BigQueryExtract deleted (redundant with BQQuery, per Phase 2.2 merge plan)
  - [x] GCSExtract deleted (unused, no render_operator, no pipeline references)
  - [x] Corresponding utility files deleted (`utils/bigquery_extract.py`, `utils/gcs_extract.py`)
  - [x] Dead utility files deleted (`utils/sql_compat.py`, `utils/logging.py`)
  - [x] Orphaned `run_read_features()` deleted from `utils/feature_store.py`
  - [x] Dead `PipelineDefinition.ml_task_groups` property deleted
  - [x] All references cleaned from builder stage map, tests, docstrings
- [x] Zero grep hits for `BigQueryExtract|GCSExtract|ReadFeatures|run_bigquery_extract|run_gcs_extract|run_read_features` in Python files
- [x] Pipeline API collapsed (REQS 11.0):
  - [x] `PipelineBuilder` class deleted — `Pipeline` is standalone with only `.add()` and `.build()`
  - [x] Named stage methods deleted (`.ingest()`, `.transform()`, `.train()`, `.evaluate()`, `.deploy()`, `.write_features()`, `.read_features()`, `.step()`)
  - [x] `stage` field removed from `PipelineStep`
  - [x] `_STAGE_MAP_BY_NAME` and `_infer_stage()` deleted
  - [x] Zero grep hits for `PipelineBuilder|_STAGE_MAP|_infer_stage|\.ingest\(|\.transform\(|\.train\(|\.evaluate\(|\.deploy\(` in Python files (excluding docs/comments)
  - [x] Exports updated: `PipelineBuilder` removed from `__init__.py` files
  - [x] `tests/pipeline/test_builder.py` deleted; useful tests moved to `test_unified_builder.py`
- [x] Component import facade: `from gcp_ml_framework.components import BQQuery, TrainModel` works
- [x] `Pipeline` exported from `gcp_ml_framework.pipeline`
- [x] CLI fixes:
  - [x] `cmd_deploy.py` does not swallow compilation errors
  - [x] `cmd_init.py` scaffolds only real CLI commands
  - [x] `cmd_init.py` writes `.python-version` as `3.12`
  - [x] `_load_pipeline()` extracted to shared `_helpers.py`
- [x] `verification_pipeline` exists with mixed @task + @ml_task steps (BQQuery → BQTransform → TrainModel)
- [x] Compiled DAG contains native Airflow operators + RunPipelineJobOperator
- [x] All tests pass, ruff clean
- [x] `gml run verification_pipeline --local` — completed on real GCP *(verified in Phase 4.5.10)*
- [x] Zero grep hits for dead code: `sql_compat|bq_to_duckdb|gcp_ml_framework.utils.logging|ml_task_groups`

---

## Phase 5: Complete ML Lifecycle — Training, Evaluation, Deployment & Monitoring [DONE]

**Status:** COMPLETE (2026-03-21). 210 tests, ruff clean, E2E compile verified.

**Why:** Full 6-step ML lifecycle (ingest → transform → train → evaluate → register → deploy) with experiment tracking and optional model monitoring. Proves the framework handles the complete data-scientist journey end-to-end.

**ADRs:** ADR-007
**Depends on:** Phase 4.5
**Detailed plan:** `docs/tasks/phase_plan.md`

**Target pipeline shape:** `BQQuery(@task) → BQTransform(@task) → Train(@ml_task) → Evaluate(@ml_task) → Register(@ml_task) → Deploy(@ml_task)`
**SmartCompiler output:** 2 BQ Airflow operators + 1 RunPipelineJobOperator → 4 KFP container steps

---

### 5.1 Fix run_deploy() Smart Model Resolution

- [x] Detect `model_uri` prefix: `projects/` → use existing registered model, `gs://` → upload new
- [x] Tests: both code paths exercised

### 5.2 Fix run_evaluate() for Regression Models

- [x] Add regression metric computation (rmse, mae, r2) alongside existing classification path
- [x] Handle models that return DataFrames (HousePredictionModel.predict())
- [x] Tests: regression metrics, classification metrics, DataFrame predictions

### 5.3 Experiment Tracking — TrainModel

- [x] Best-effort logging in `TrainModel.execute()` after `run()` completes
- [x] Log non-internal fields as params to Vertex AI Experiments
- [x] Use `resume=True` on `start_run()` for idempotency
- [x] Tests: experiment params logged, failure is non-fatal

### 5.4 Experiment Tracking — EvaluateModel

- [x] Best-effort metric logging in `EvaluateModel.execute()`
- [x] Same run_id as TrainModel for continuity (both params + metrics on one run)
- [x] Remove duplicate experiment logging from `run_evaluate()` utility
- [x] Tests: metrics logged, failure is non-fatal

### 5.5 Add Monitoring Fields to DeployModel

- [x] Optional fields: `enable_monitoring`, `monitoring_alert_email`, `monitoring_log_sample_rate`, `monitoring_monitor_interval`, `monitoring_skew_thresholds`, `monitoring_drift_thresholds`
- [x] All disabled by default
- [x] Tests: defaults, enabled configuration

### 5.6 Update run_deploy() and DeployModel for Monitoring

- [x] After deployment, if `enable_monitoring=True`, create Model Deployment Monitoring Job
- [x] Configure skew/drift detection thresholds from fields
- [x] Update `DeployModel.run()` / `execute()` to pass all `self.monitoring_*` fields through to `run_deploy()`
- [x] Tests: monitoring job created/not created based on flag

### 5.7 Create Evaluation Step Subclasses

- [x] `HouseEvaluateStep(EvaluateModel)` — overrides `run()` for housing regression
- [x] `EvaluateVerifyStep(EvaluateModel)` — same pattern for verification pipeline
- [x] Handles HousePredictionModel.predict() DataFrame output
- [x] Gate logic: lower-is-better for rmse/mae, higher-is-better for r2
- [x] **Important:** `run()` must construct eval table from `self.dataset + ".training_features"` (not `self.dataset_uri`) — in KFP, @task outputs don't flow into the KFP pipeline without 5.15 bridging; this is the fallback for steps that know their source table

### 5.8 Add serving_container_image Defaults to Compiler

- [x] `_build_derived_params()` auto-populates sklearn serving container for RegisterModel/DeployModel
- [x] Explicit values override the default
- [x] Tests: default populated, explicit value preserved
- [x] **Risk:** HousePredictionModel.predict() returns DataFrame (not ndarray). Verify Vertex AI pre-built sklearn container handles this during E2E. If not, use Custom Prediction Routine (CPR) container or adjust model interface.

### 5.9 Wire Full training_pipeline (6 Steps)

- [x] Create `pipelines/training_pipeline/steps.py` with HouseTrainModelStep + HouseEvaluateStep
- [x] Update `pipeline.py`: ingest → transform → train → evaluate → register → deploy
- [x] Update or simplify `training_pipeline_features.sql` — must read from `{dataset}.training_features` (the table BQTransform creates), not the raw housing table
- [x] Tests: 6 steps, correct types, correct order

### 5.10 Expand verification_pipeline (6 Steps)

- [x] Add evaluate, register, deploy steps
- [x] Deploy step has `enable_monitoring=True` to demonstrate capability
- [x] Relaxed gate thresholds for verification (rmse: 200000)
- [x] Tests: 6 steps, monitoring enabled on deploy step

### 5.11 Fix Cross-Step Wiring (RegisterModel → DeployModel)

- [x] Compiler: RegisterModel output → `last_model_output` (not `last_dataset_output`)
- [x] LocalRunner: same change
- [x] Result: DeployModel receives resource_name → smart resolution skips re-upload
- [x] Tests: wiring verified in both compiler and LocalRunner

### 5.12 Tests

- [x] All new unit tests pass (target: 180+)
- [x] Existing tests updated for new pipeline shapes
- [x] Ruff clean across entire codebase

### 5.13 Full E2E Verification (6-Step Pipelines)

- [x] `gml compile --all` produces valid DAGs and KFP YAML
- [x] DAGs have correct structure (2 BQ operators + 1 RunPipelineJobOperator)
- [x] KFP YAML has 4 container steps (train, evaluate, register, deploy)
- [x] RunPipelineJobOperator `parameter_values` includes bridged `dataset_uri` from @task group
- [x] `gml run verification_pipeline --local` — all 6 steps complete
- [x] `gml run training_pipeline --local` — all 6 steps complete
- [x] Model registered in Vertex AI Model Registry
- [x] Endpoint created, model deployed
- [x] Experiment run visible (params + metrics)
- [x] Monitoring job created for verification pipeline

### 5.14 BQQuery Output Tracking

- [x] Add `output_uri_path` writing to `BQQuery.execute()` — write the full BQ table path (`{project}.{dataset}.{destination_table}`)
- [x] Consistent with BQTransform which already writes `{project}.{dataset}.{output_table}`
- [x] Enables cross-step data flow from BQQuery → downstream steps
- [x] Tests: BQQuery.execute() writes destination table reference to output_uri_path

### 5.15 @task → @ml_task Data Bridging in SmartCompiler

**Why (from discussion.md):** "From @task to @ml_task: The Airflow DAG passes the BQ table reference as a parameter to the Vertex AI pipeline." This is documented as a capability but not yet implemented. Without it, `dataset_uri` is empty for @ml_task steps that follow @task steps in the compiled DAG.

- [x] SmartCompiler tracks `last_dataset_output` and `last_model_output` across ALL step groups (not just within KFP)
- [x] At @task→@ml_task boundary: compute the last @task step's output reference (deterministic — known at compile time from `destination_table`/`output_table` fields)
- [x] Pass bridged values as `parameter_values` in RunPipelineJobOperator (alongside existing `run_date`)
- [x] KFP pipeline definition accepts bridged values as input parameters
- [x] Within KFP, first step with matching field (`dataset_uri`, `model_uri`) receives the bridged value
- [x] At @ml_task→@task boundary: capture KFP pipeline output via RunPipelineJobOperator XCom for downstream @task steps
- [x] LocalRunner: no changes needed (already runs all steps in-process with full wiring)
- [x] Tests: compiled DAG contains bridged parameter_values, KFP YAML accepts them as inputs

### 5.16 Mixed Execution Scenario Test

**Why:** Proves the SmartCompiler handles the edge case from discussion.md: "@ml_task, @task, @ml_task = two separate Vertex AI pipelines with an Airflow task between them." Validates both bridging directions.

- [x] Create `pipelines/mixed_test_pipeline/pipeline.py` with pattern: `@task → @ml_task → @task → @ml_task`
  - Example: BQQuery(@task) → Train(@ml_task) → BQTransform(@task) → Deploy(@ml_task)
- [x] SmartCompiler produces: 4 Airflow tasks (BQ op → RunPipelineJobOp1 → BQ op → RunPipelineJobOp2)
- [x] Data bridges correctly at each @task↔@ml_task boundary
- [x] `gml compile mixed_test_pipeline` succeeds
- [x] Unit tests verify DAG structure and parameter bridging

### 5.17 Full E2E Verification (Mixed + Bridging)

- [x] All bridging tests pass
- [x] Mixed pipeline compiles correctly
- [x] All unit tests pass (target: 180+)
- [x] Ruff clean across entire codebase
- [x] `gml run verification_pipeline --local` — EvaluateModel receives `dataset_uri` via bridging
- [x] `gml run training_pipeline --local` — same verification

---

### Phase 5 Definition of Done

- [x] Both pipelines have 6 active steps (ingest, transform, train, evaluate, register, deploy)
- [x] Smart compiler produces: Airflow DAG with 2 BQ operators + RunPipelineJobOperator (4 ML steps)
- [x] @task→@ml_task data bridging works: RunPipelineJobOperator receives `parameter_values` with bridged outputs
- [x] Mixed @task/@ml_task pipeline compiles correctly (two separate KFP pipelines with Airflow task between)
- [x] BQQuery writes output_uri_path (consistent with BQTransform)
- [x] Each step has unit tests (180+ total)
- [x] `gml run` executes full pipeline for both pipelines
- [x] Full pipeline runs on Vertex AI
- [x] Model registered in Model Registry
- [x] Model deployed to endpoint
- [x] Experiment run logged with params + metrics
- [x] Model monitoring enabled (optional, demonstrated on verification_pipeline)
- [x] run_deploy() handles both GCS paths and registered model resource names
- [x] DeployModel.run() passes monitoring fields through to run_deploy()

---

## Phase 5.5: Dedicated Serving Image (CPR) [DONE]

**Status:** COMPLETE (2026-03-21). 226 tests, ruff clean, serving images built and deployed.

**Why:** Pre-built `sklearn-cpu.1-3:latest` serving container can't unpickle `HousePredictionModel` because it lacks the `second_run` package. Vertex AI logs: `ModuleNotFoundError: No module named 'second_run'`. This was flagged as a risk in Phase 5.8 and proved to be a blocking production issue.

**Solution:** Build a dedicated lightweight serving Docker image alongside the pipeline image with CPR (Custom Prediction Routines).

**Depends on:** Phase 5

---

### 5.5.1 Prediction Handler

- [x] `gcp_ml_framework/serving/__init__.py` — empty init
- [x] `gcp_ml_framework/serving/handler.py` — Generic HTTP prediction server (~100 lines)
  - Downloads `model.pkl` from `AIP_STORAGE_URI` (GCS) on startup
  - `GET /health` → 200 `{"status": "healthy"}`
  - `POST /predict` → `{"instances": [...]}` → `{"predictions": [...]}`
  - Uses stdlib `http.server.HTTPServer` — no Flask/FastAPI dependency

### 5.5.2 Serving Dockerfile

- [x] `docker/serving/Dockerfile` — slim serving image
  - Based on `base-python` (same base as pipeline image)
  - Only runtime deps: `scikit-learn`, `pandas`, `numpy`, `google-cloud-storage`, `loguru`
  - Copies only `second_run/` + `gcp_ml_framework/serving/`

### 5.5.3 Cloud Build Integration

- [x] `cloudbuild.yaml` Steps 6-8: Pull/Build/Push `{pipeline}-serving` image
- [x] `scripts/docker_build.sh` — Added `_build_serving()` function

### 5.5.4 Compiler Default

- [x] `compiler.py` — Computes `serving_image` alongside `base_image`; defaults RegisterModel/DeployModel to serving image instead of `sklearn-cpu.1-3:latest`

### 5.5.5 CPR Routes

- [x] `register.py` — Adds CPR kwargs for custom containers (predict route, health route, command, ports)
- [x] `vertex.py` — Same CPR detection for GCS-upload path in `run_deploy()`
- [x] Pre-built Vertex AI images (`us-docker.pkg.dev/vertex-ai/`) skip CPR kwargs

### 5.5.6 Tests

- [x] `tests/serving/test_handler.py` — 8 tests (health, predict, error handling, model loading)
- [x] `tests/pipeline/test_compiler.py` — 3 new tests (serving image default, explicit override)
- [x] `tests/components/test_register.py` — 2 new tests (CPR kwargs, pre-built skip)
- [x] `tests/utils/test_vertex.py` — 3 new tests (CPR kwargs, pre-built skip, registered model)

### 5.5.7 E2E Verification

- [x] `gml compile --all` — YAML uses `{pipeline}-serving:tag`, not sklearn
- [x] `gml build training_pipeline` — Both pipeline + serving images built (Cloud Build)
- [x] `gml build verification_pipeline` — Both pipeline + serving images built
- [x] Serving images verified in Artifact Registry (`training-pipeline-serving`, `verification-pipeline-serving`)
- [x] `gml deploy --all` — All 4 images verified, DAGs + YAML uploaded
- [x] `gml run training_pipeline` — Composer DAG triggered
- [x] `gml run verification_pipeline` — Composer DAG triggered

### Phase 5.5 Definition of Done

- [x] Serving handler implements Vertex AI CPR protocol (/health, /predict)
- [x] Slim serving Dockerfile exists with only runtime deps
- [x] Cloud Build builds both pipeline + serving images
- [x] Compiler defaults to serving image (not sklearn)
- [x] CPR routes added for custom containers in RegisterModel and run_deploy()
- [x] Pre-built Vertex AI images skip CPR kwargs
- [x] 226 unit tests passing, ruff clean
- [x] Both serving images built and deployed to Artifact Registry
- [x] Both pipelines triggered via Composer

---

## Phase 6: Advanced Pipeline Features

**REQS:** 11.0 (Simplify API), 14.0 (Standard Variables), 22.0 (Conditional/Loop)
**Depends on:** Phase 2
**Parallel with:** Phase 4, 5

---

### 6.1 Expose Standard Variables as Env Vars (REQS 14.0)

**What:** Data scientists access `os.environ["GML_ENVIRONMENT"]` inside `run()`.

- [ ] Define standard variables: GML_PROJECT, GML_REGION, GML_TEAM, GML_PROJECT_NAME, GML_BRANCH, GML_ENVIRONMENT, GML_PIPELINE, GML_NAMESPACE
- [ ] In SmartCompiler: for @ml_task groups, set env vars on KFP tasks via `task.set_env_variable()`
- [ ] In DAG compiler: for @task steps, pass as Airflow operator params or env
- [ ] In LocalRunner: set env vars in os.environ before calling execute()
- [ ] Tests: verify compiled YAML contains env vars, verify execute() can read them

### 6.2 Conditional Operators (REQS 22.0)

**What:** `.condition()` on Pipeline builder maps to `dsl.Condition` in KFP.

- [ ] Design API:
  ```python
  .condition(
      when="Evaluate.gate_passed == true",
      if_true=[RegisterModel(), DeployModel()],
      if_false=[],
  )
  ```
- [ ] Extend PipelineDefinition with ConditionNode
- [ ] Update SmartCompiler to emit `dsl.Condition` in KFP pipeline
- [ ] Update LocalRunner to evaluate predicate and run appropriate branch
- [ ] TDD: builder tests, compiler tests, local runner tests

### 6.3 Loop Operators (REQS 22.0)

**What:** `.for_each()` on Pipeline builder maps to `dsl.ParallelFor` in KFP.

- [ ] Design API:
  ```python
  .for_each(
      items_from="Get Brands",
      steps=[BQTransform(...), TrainModel(...)],
  )
  ```
- [ ] Extend PipelineDefinition with ForEachNode
- [ ] Update SmartCompiler to emit `dsl.ParallelFor`
- [ ] Update LocalRunner to iterate sequentially
- [ ] TDD: builder tests, compiler tests

### 6.4 E2E Test

- [ ] Create test pipeline with condition or for_each
- [ ] Compile → Run on Vertex AI → Verify control flow execution

---

### Phase 6 Definition of Done

- [ ] Standard env vars injected into all container steps
- [ ] `.condition()` compiles to dsl.Condition, runs locally
- [ ] `.for_each()` compiles to dsl.ParallelFor, runs locally
- [ ] E2E test with control flow passes on Vertex AI

---

## Phase 7: DBT Integration

**ADRs:** ADR-006
**REQS:** 19.0
**Depends on:** Phase 2
**Parallel with:** Phase 4, 5, 6

---

### 7.1 Create DbtRun Component

**TDD — tests first:**
- [ ] `tests/components/test_dbt.py`:
  - DbtRun instantiation with project_dir, target, models, full_refresh
  - DbtRun._task_type == TaskType.TASK
  - render_operator() produces BashOperator with correct dbt command
  - execute() runs dbt CLI for local execution

**Then implement:**
- [ ] Create `gcp_ml_framework/components/dbt/dbt_run.py`:
  ```python
  @task
  class DbtRun(BaseComponent):
      project_dir: str = "dbt/"
      target: str = ""        # Resolved from environment at compile time
      models: str = ""        # Optional: specific models
      full_refresh: bool = False
      profiles_dir: str = ""  # Auto-generated

      def execute(self):
          """Run dbt locally (for gml run --local)."""
          cmd = f"dbt run --project-dir {self.project_dir} --target {self.target}"
          if self.models: cmd += f" --models {self.models}"
          if self.full_refresh: cmd += " --full-refresh"
          subprocess.run(cmd, shell=True, check=True)

      def render_operator(self, context):
          """Generate BashOperator for Airflow."""
          return f'BashOperator(task_id="{self.component_name}", bash_command="{cmd}")'
  ```

### 7.2 Auto-Generate profiles.yml

- [ ] Create `gcp_ml_framework/utils/dbt.py`:
  - `generate_profiles(context) -> str`: generates profiles.yml from .env
  - Maps GML environments to dbt targets
  - BQ project/dataset from context

### 7.3 Update gml init for DBT

- [ ] Update `gcp_ml_framework/cli/cmd_init.py`:
  - `gml init pipeline <name> --dbt` scaffolds:
    ```
    pipelines/<name>/dbt/
    ├── dbt_project.yml
    ├── profiles.yml         (auto-generated)
    ├── models/
    │   ├── staging/         (raw → clean)
    │   └── marts/           (clean → features)
    └── tests/
    ```

### 7.4 Composer DBT Setup

- [ ] Document: Composer needs `dbt-bigquery>=1.7` in PyPI packages
- [ ] Update `terraform/modules/composer/variables.tf`: add dbt to default pypi_packages

### 7.5 Reference Implementation

- [ ] Add `dbt/` directory to training_pipeline with simple model:
  - `models/staging/stg_housing_raw.sql` — SELECT * FROM raw table
  - `models/marts/housing_features.sql` — Feature engineering SQL using `{{ ref('stg_housing_raw') }}`
- [ ] Show in pipeline.py:
  ```python
  pipeline = (
      Pipeline(name="training_pipeline", schedule="@daily")
      .add(DbtRun(project_dir="dbt/", models="marts.housing_features"), name="Transform Features")
      .add(TrainHouseModel(machine_type="n2-standard-4"), name="Train")
      .add(EvaluateModel(...), name="Evaluate")
      .add(RegisterModel(), name="Register")
      .build()
  )
  ```

---

### Phase 7 Definition of Done

- [ ] `DbtRun` component exists with @task default
- [ ] `profiles.yml` auto-generated from .env
- [ ] `gml init pipeline --dbt` scaffolds DBT project
- [ ] Reference `dbt/` project in training_pipeline
- [ ] Composer Terraform includes dbt-bigquery dependency
- [ ] Pipeline with DbtRun step compiles and runs locally
- [ ] Pipeline with DbtRun deploys to Composer and triggers DBT successfully

---

## Phase 8: Polish (P1 + P2 Requirements)

**REQS:** 3.0, 9.0, 10.0, 17.0, 20.0
**ADRs:** ADR-010
**Parallel with:** Everything after Phase 1

---

### 8.1 Structured Logging (REQS 9.0)

- [ ] Find all `print()` in gcp_ml_framework/: `uv run -- ruff check gcp_ml_framework/ --select T201`
- [ ] Replace each with appropriate `loguru.logger` call
- [ ] Configure in BaseComponent.cli():
  - Non-local environments: `logger.add(sys.stdout, serialize=True)` (JSON for Cloud Logging)
  - Local/dev: human-readable format with timestamps
- [ ] Test: verify log output format

### 8.2 DAG Cleanup (REQS 3.0)

- [ ] Verify `gml teardown` removes DAG files from Composer bucket + Airflow metadata
- [ ] Test: create branch DAG, teardown, verify deleted
- [ ] Verify `teardown.yaml` GitHub Actions workflow handles stale branches

### 8.3 Mypy Annotations (REQS 17.0)

- [ ] Run `uv run -- mypy gcp_ml_framework/ --ignore-missing-imports` — catalog errors
- [ ] Fix type errors in core modules first: config, context, naming
- [ ] Add return type annotations where missing
- [ ] Target: `mypy gcp_ml_framework/ --warn-return-any` passes

### 8.4 Google-Style Docstrings (REQS 10.0)

Priority classes (public API that data scientists use):
- [ ] `BaseComponent`, `@task`, `@ml_task`
- [ ] `TrainModel`, `EvaluateModel`, `RegisterModel`, `DeployModel`
- [ ] `BQQuery`, `BQTransform`, `DbtRun`, `Email`
- [ ] `Pipeline`, `PipelineDefinition`, `PipelineStep`
- [ ] `MLContext`, `FrameworkConfig`, `Environment`, `NamingConvention`

Priority methods:
- [ ] `BaseComponent.cli()`, `.execute()`, `.run()`, `.as_kfp_component()`, `.render_operator()`
- [ ] `Pipeline.add()`, `.build()`, `.for_each()`, `.condition()`
- [ ] `load_config()`, `MLContext.from_config()`

### 8.5 Cost Labels (ADR-010)

- [ ] Add `resource_labels` property to `NamingConvention`
- [ ] Apply labels in `VertexRunner.submit()` (PipelineJob labels)
- [ ] Apply labels in `gml build` (Cloud Build substitutions)
- [ ] Apply labels in component execute() methods (BQ job labels)
- [ ] Verify: labels visible in GCP console and billing export

### 8.6 AGENTS.md (REQS 20.0)

- [ ] Create `AGENTS.md`:
  - Framework architecture overview (unified @task/@ml_task model)
  - How to create a new pipeline
  - How to create a custom step (subclass + override run())
  - Component lifecycle: cli → execute → run
  - Naming conventions and branch isolation
  - Testing patterns (3-tier)

---

### Phase 8 Definition of Done

- [ ] Zero `print()` calls in gcp_ml_framework/
- [ ] Cloud Logging JSON format in staging/prod containers
- [ ] `gml teardown` verified working for stale DAG cleanup
- [ ] `mypy gcp_ml_framework/ --warn-return-any` passes
- [ ] All public API classes/methods have Google-style docstrings
- [ ] Cost labels applied to Vertex AI runs, Cloud Build, BQ jobs
- [ ] `AGENTS.md` exists with comprehensive framework guide

---

## REQS.docx Coverage Matrix

| ID | Requirement | Priority | Status | Phase | Notes |
|---|---|---|---|---|---|
| 1.0 | Unified Component Lifecycle | P0 | **DONE** | **Phase 4.5** | execute()→run() fixed on all ML components |
| 2.0 | Underscore Normalization | P1 | **DONE** | — | Terraform local.project_slug |
| 3.0 | Cleanout Invalid DAGs | P1 | Not Done | **Phase 8** | Verify gml teardown handles this |
| 4.0 | Docker Build Tag Issue | P1 | **DONE** | — | Tags are {branch}-{short_sha} |
| 5.0 | Airflow DAG 403 Permission | P0 | **DONE** | — | Terraform IAM bindings |
| 6.0 | YAML Embeds Python Source | P0 | **DONE** | — | Container components, no inlined Python |
| 7.0 | Pydantic Migration | P0 | **DONE** | — | All dataclasses → Pydantic |
| 8.0 | Replace Argparse with Typer | P0 | **DONE** | — | BaseComponent.cli(), gml CLI |
| 9.0 | Structured Logging | P1 | Partial | **Phase 8** | Replace print() with loguru |
| 10.0 | Google-Style Docstrings | P2 | Partial | **Phase 8** | Public API priority |
| 11.0 | Simplify PipelineBuilder API | P0 | **DONE** | **Phase 4.5** | PipelineBuilder deleted, Pipeline.add() is the only API |
| 12.0 | Refactor CLI Entrypoints | P0 | **DONE** | — | python -m step_module --help |
| 13.0 | Flatten ComponentConfig | P0 | **DONE** | **Phase 1** | Merged into BaseComponent |
| 14.0 | Expose Standard Variables | P0 | Partial | **Phase 6** | GML_* env vars in containers |
| 15.0 | Rename GitState to Environment | P0 | **DONE** | **Phase 1** | 6-value enum, CI/CD-owned |
| 16.0 | Separate CI/CD from Framework | P1 | **DONE** | **Phase 1** | Removed _resolve_git_state() |
| 17.0 | Enforce Mypy Annotations | P2 | Not Done | **Phase 8** | --warn-return-any first |
| 18.0 | Docker Cloud Build | P1 | **DONE** | **Phase 3** | gml build + Cloud Build everywhere |
| 18.0b | Simplify Docker Hierarchy | P1 | **DONE** | **Phase 3** | 2-layer: base-python → pipeline |
| 19.0 | DBT Integration | P2 | Not Done | **Phase 7** | First-class DbtRun component |
| 20.0 | AGENTS.md | P2 | Not Done | **Phase 8** | AI coding guidelines |
| 21.0 | Model Registry Step | P0 | **DONE** | **Phase 1** | RegisterModel component |
| 22.0 | Conditional/Loop Operators | P0 | Not Done | **Phase 6** | .for_each() + .condition() |

**Score after completion: 23/23 requirements addressed.**

---

## Review

### Phase 1 Review (2026-03-20)

**Result:** 78 unit tests, all passing. Compiler unblocked, environment overhauled, config flattened.

| Item | REQS | Verified |
|---|---|---|
| RegisterModel component | 21.0 | `from gcp_ml_framework.pipeline.compiler import PipelineCompiler` succeeds |
| ComponentConfig flattened | 13.0 | `grep -r "class ComponentConfig" gcp_ml_framework/` returns nothing |
| GitState → Environment | 15.0, 16.0 | `grep -r "GitState\|_resolve_git_state" gcp_ml_framework/` returns nothing |
| Test infrastructure | — | 78 unit tests in 0.4s, organized by functionality |
| .env.example | — | Exists with all GML_* variables |

**Items deferred to Phase 4:** `gml context show` and `gml compile training_pipeline` require a real `.env` with GCP project IDs.

---

### Phase 2 Review (2026-03-20)

**Result:** 128 → 127 unit tests (after Phase 2.5 cleanup). Unified task architecture complete.

| Item | REQS | Verified |
|---|---|---|
| @task / @ml_task decorators | 11.0 | `from gcp_ml_framework import Pipeline, task, ml_task, TaskType` succeeds |
| Unified BQQuery, Email components | 11.0 | Both have render_operator() for Airflow, execute() for local |
| Pipeline.add() builder | 11.0 | Replaces PipelineBuilder + DAGBuilder with single API |
| SmartCompiler | — | Auto-groups @ml_task → KFP YAML, @task → Airflow operator |
| LocalRunner | — | `gml run --local` handles all task types |
| training_pipeline migrated | — | Uses `Pipeline.add()` API |
| Old DAG system deleted | — | 11 files in dag/, 2 files in tests/dag/ removed |
| Pydantic warnings fixed | — | 0 DeprecationWarnings with `-W error::DeprecationWarning` |
| Ruff clean | — | 0 errors across entire gcp_ml_framework/ and tests/ |

**Final state:** 127 tests in 0.39s, 0 ruff errors, 0 Pydantic warnings, 0 old DAG references.
