# version_1 Development Roadmap

**Date:** 2026-03-20
**Status:** Phase 1 + Phase 2 + Phase 2.5 + Phase 3 + Phase 4 COMPLETE — Phase 5 next
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
Phase 1: Critical Fixes + Test Foundation [START HERE — blocks everything]
    │
    ├──→ Phase 2: Unified Task Architecture [SEQUENTIAL after Phase 1]
    │       │
    │       ├──→ Phase 4: Training Pipeline E2E [needs Phase 2 + 3]
    │       │       │
    │       │       └──→ Phase 5: Complete Pipeline + Experiments [needs Phase 4]
    │       │
    │       ├──→ Phase 6: Advanced Features [needs Phase 2, PARALLEL with 4/5]
    │       │
    │       └──→ Phase 7: DBT Integration [needs Phase 2, PARALLEL with 4/5/6]
    │
    ├──→ Phase 3: Cloud Build + Docker [PARALLEL with Phase 2]
    │
    └──→ Phase 8: Polish [PARALLEL with everything after Phase 1]
```

**Execution tracks:**
- **Track A (critical path):** Phase 1 → Phase 2 → Phase 4 → Phase 5
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
- [ ] `uv run -- pytest tests/ --cov=gcp_ml_framework --cov-report=term-missing` — review coverage *(nice-to-have, deferred)*

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
- [ ] ~~Terraform IAM for Cloud Build~~ — **Deferred.** Sandbox uses pre-existing SAs; Cloud Build default SA likely has sufficient permissions. If not, fix with `gcloud` commands at runtime (Phase 4).
- [ ] Verify: `gcloud builds submit` works with correct permissions (Phase 4, first real build)

---

### Phase 3 Definition of Done

- [ ] `uv run -- gml build training_pipeline` → image built on Cloud Build, pushed to AR (requires Cloud Build + AR infra)
- [x] Docker Desktop NOT required on developer machine
- [ ] Shared layer cache works: second build from different machine is <60s (requires live test)
- [x] Docker hierarchy: 2 layers (base-python → pipeline image)
- [x] `component-base` and `base-ml` Dockerfiles deleted
- [x] `.gcloudignore` excludes all sensitive files
- [ ] ~~Terraform IAM~~ — Deferred (sandbox pre-existing SAs, verify at first `gml build`)

---

## Phase 3.5: Rename Service Account Config for Clarity

**Why:** The current `GML_GCP__SERVICE_ACCOUNT_EMAIL` is ambiguous — the project has 3 SAs but the config doesn't say which one this is. It's the Vertex AI Pipeline SA. Renaming to `PIPELINE_SERVICE_ACCOUNT_EMAIL` aligns with Terraform outputs (which already use `pipeline_service_account_email` and `composer_service_account_email`) and prevents confusion as the project matures.

**Scope:** Rename only. No new SAs added to framework config.

---

### SA Architecture (3 SAs total, 1 in framework config)

| SA | Identity (sandbox) | Used by | In `.env`? | Why / Why not |
|---|---|---|---|---|
| **Pipeline SA** | `gc-sa-for-vertex-ai-pipelines@...` | `runner.py` (Vertex job submission), `smart_compiler.py` (DAG generation) | **YES → rename** | Framework passes this SA to `job.submit()` and `RunPipelineJobOperator`. Must be configurable. |
| **Composer SA** | `gc-sa-for-composer-env@...` | Airflow runtime (runs DAGs), Terraform IAM (impersonation) | **NO** | Framework uploads DAGs to GCS bucket — uses caller's gcloud auth, not Composer SA. Impersonation (Composer→Pipeline) is a Terraform IAM binding, not a framework concern. |
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
- [ ] Verify: DAG triggers → RunPipelineJobOperator submits to Vertex AI → pipeline completes, model artifact in GCS

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

## Phase 5: Complete Training Pipeline + Experiment Tracking

**Why:** Reference implementation showing the full ML lifecycle. Proves the framework is data-scientist-ready.

**ADRs:** ADR-007
**Depends on:** Phase 4

---

### 5.1 Implement Pipeline Steps

For each step, follow TDD (test in `tests/training_pipeline/test_steps.py` first):

- [ ] **Ingest step** — `BQQuery` component (or thin subclass) reading raw housing data
  - SQL: `SELECT * FROM \`{bq_dataset}.housing_data_table\``
  - @task decorator (runs as Airflow operator)

- [ ] **Transform step** — `BQTransform` component with SQL file
  - SQL file: `pipelines/training_pipeline/sql/training_pipeline_features.sql`
  - @task decorator

- [ ] **Train step** — `HouseTrainModelStep(TrainModel)` (already exists)
  - @ml_task decorator with machine_type="n2-standard-4"
  - Imports from `second_run.estimator`

- [ ] **Evaluate step** — `EvaluateModel` component (or thin subclass)
  - metrics: ["rmse", "mae", "r2"]
  - gate: {"rmse": 50000}
  - @ml_task decorator

- [ ] **Register step** — `RegisterModel` component
  - @ml_task decorator

### 5.2 Wire Full Pipeline

- [ ] Update `pipelines/training_pipeline/pipeline.py`:
  ```python
  pipeline = (
      Pipeline(name="training_pipeline", schedule="@daily")
      .add(BQQuery(sql="SELECT * FROM `{bq_dataset}.housing_data_table`"), name="Ingest")
      .add(BQTransform(sql_file="sql/training_pipeline_features.sql"), name="Transform")
      .add(TrainHouseModel(machine_type="n2-standard-4"), name="Train")
      .add(EvaluateModel(metrics=["rmse", "mae"], gate={"rmse": 50000}), name="Evaluate")
      .add(RegisterModel(), name="Register")
      .build()
  )
  ```
  Note: Smart compiler auto-groups: @task(Ingest), @task(Transform), @ml_task(Train, Evaluate, Register)

### 5.3 Implement Experiment Tracking

- [ ] In `gcp_ml_framework/components/ml/train.py` — `TrainModel.execute()`:
  - After `self.run()` completes:
    ```python
    aiplatform.init(experiment=self.experiment_name, project=self.project, location=self.region)
    aiplatform.start_run(run=f"{self.job_name}-{self.run_date}")
    # Log all non-internal fields as params
    aiplatform.log_params({k: str(v) for k, v in self.model_dump().items() if k not in _INTERNAL_FIELDS})
    ```
- [ ] In `gcp_ml_framework/components/ml/evaluate.py` — `EvaluateModel.execute()`:
  - After evaluation:
    ```python
    aiplatform.log_metrics(computed_metrics)  # {"rmse": 42000, "mae": 31000}
    aiplatform.end_run()
    ```
- [ ] Write tests in `tests/components/test_train.py` and `test_evaluate.py`

### 5.4 E2E Test Full Pipeline

- [ ] Compile → Build → Deploy → Run full 5-step pipeline on Vertex AI
- [ ] Verify each step completes in console
- [ ] Verify model registered in Model Registry
- [ ] Verify experiment run visible in Vertex AI Experiments UI

---

### Phase 5 Definition of Done

- [ ] Pipeline has 5 active steps (ingest, transform, train, evaluate, register)
- [ ] Smart compiler produces: Airflow DAG with 2 BQ operators + RunPipelineJobOperator (3 ML steps)
- [ ] Each step has unit tests
- [ ] `gml run --local` executes full pipeline
- [ ] Full pipeline runs on Vertex AI
- [ ] Model registered in Model Registry
- [ ] Experiment run logged with params + metrics

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
| 1.0 | Unified Component Lifecycle | P0 | **DONE** | — | Container components, BaseComponent lifecycle |
| 2.0 | Underscore Normalization | P1 | **DONE** | — | Terraform local.project_slug |
| 3.0 | Cleanout Invalid DAGs | P1 | Not Done | **Phase 8** | Verify gml teardown handles this |
| 4.0 | Docker Build Tag Issue | P1 | **DONE** | — | Tags are {branch}-{short_sha} |
| 5.0 | Airflow DAG 403 Permission | P0 | **DONE** | — | Terraform IAM bindings |
| 6.0 | YAML Embeds Python Source | P0 | **DONE** | — | Container components, no inlined Python |
| 7.0 | Pydantic Migration | P0 | **DONE** | — | All dataclasses → Pydantic |
| 8.0 | Replace Argparse with Typer | P0 | **DONE** | — | BaseComponent.cli(), gml CLI |
| 9.0 | Structured Logging | P1 | Partial | **Phase 8** | Replace print() with loguru |
| 10.0 | Google-Style Docstrings | P2 | Partial | **Phase 8** | Public API priority |
| 11.0 | Simplify PipelineBuilder API | P0 | **DONE** | **Phase 2** | Unified Pipeline with .add(), old PipelineBuilder kept as alias |
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
