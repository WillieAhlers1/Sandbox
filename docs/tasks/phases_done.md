# Completed Phases

## Phase 1: Critical Fixes + Test Foundation

**Completed:** 2026-03-20
**Verification:** 78 unit tests passing, zero old references, compiler imports clean
**REQS addressed:** 13.0 (ComponentConfig), 15.0 (GitState→Environment), 16.0 (CI/CD separation), 21.0 (RegisterModel)

### Task 1.1 — Test Infrastructure
- Added pytest>=8.0, pytest-cov>=5.0 to `[project.optional-dependencies.dev]`
- Added `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.mypy]` to pyproject.toml
- Created test directory structure: tests/{config,components,pipeline,cli}/ with __init__.py
- Created tests/conftest.py with 4 fixtures: mock_naming, mock_gcp_config, mock_framework_config, mock_context

### Task 1.2 — RegisterModel Component (REQS 21.0)
- Created `gcp_ml_framework/components/ml/register.py` — RegisterModel(BaseComponent)
- Fields: model_uri, model_display_name, serving_container_image, labels, description
- execute() calls aiplatform.Model.upload(), writes resource_name to output_uri_path
- Unblocked `from gcp_ml_framework.pipeline.compiler import PipelineCompiler`

### Task 1.3 — Flatten ComponentConfig (REQS 13.0)
- Deleted `ComponentConfig` class from base.py
- Moved 6 fields to BaseComponent: machine_type, accelerator_type, accelerator_count, timeout_seconds, retry_count, cache_enabled
- timeout_seconds, retry_count, cache_enabled added to _INTERNAL_FIELDS; machine_type left as regular field (used by KFP)
- Cleaned 7 component files: train.py, evaluate.py, deploy.py, bigquery_extract.py, gcs_extract.py, bq_transform.py, write_features.py
- TrainModel duplicate machine_type/accelerator fields removed (inherited from base)
- DeployModel keeps its own machine_type="n2-standard-2" override

### Task 1.4 — Environment Overhaul (REQS 15.0, 16.0)
- Renamed GitState → Environment(StrEnum) with values: LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT
- Deleted _resolve_git_state() function entirely
- Added `environment: str = "dev"` to FrameworkConfig (pydantic-settings reads GML_ENVIRONMENT)
- Added `test_project_id: str = ""` to GCPConfig
- Updated _validate_projects() and active_gcp_project to use Environment enum
- Updated context.py: git_state → environment field
- Updated pipeline/compiler.py, dag/compiler.py, cli/cmd_deploy.py, cli/cmd_teardown.py, cli/cmd_context.py

### Task 1.5 — Tests (78 unit tests)
- tests/config/test_config.py — 11 tests (Environment enum, FrameworkConfig validation, active_gcp_project)
- tests/config/test_context.py — 9 tests (MLContext creation, properties, is_production, frozen)
- tests/config/test_naming.py — 19 tests (_slugify, _bq_safe, NamingConvention, all resource names)
- tests/components/test_base.py — 8 tests (flat fields, _INTERNAL_FIELDS, CLI exclusion, run/execute)
- tests/components/test_train.py — 4 tests (instantiation, machine_type inheritance, execute lifecycle)
- tests/components/test_evaluate.py — 3 tests (instantiation, default metrics, execute delegation)
- tests/components/test_register.py — 4 tests (instantiation, isinstance, execute upload, output_uri)
- tests/components/test_deploy.py — 4 tests (instantiation, machine_type override, traffic_split, execute)
- tests/pipeline/test_builder.py — 6 tests (chaining, build, empty raises, stages, names)
- tests/pipeline/test_compiler.py — 4 tests (import, context params, environment, derived params)
- tests/dag/test_compiler.py — 4 tests (valid python, DEV schedule None, non-DEV schedule, imports)
- tests/cli/test_commands.py — 2 tests (module import smoke tests)

### Task 1.6 — .env.example
- Created .env.example with all GML_* variables, comments, no real values

---

## Phase 2: Unified Task Architecture

**Completed:** 2026-03-20
**Verification:** 128 unit tests passing (50 new), ruff clean, training_pipeline migrated
**REQS addressed:** 11.0 (Simplify PipelineBuilder API → Pipeline.add())

### Task 2.1 — Decorators
- Created `gcp_ml_framework/decorators.py` — TaskType(StrEnum), @task, @ml_task decorators
- @ml_task supports resource param overrides (machine_type, accelerator_type, accelerator_count) with model_rebuild()
- Added `_task_type: ClassVar[TaskType] = TaskType.ML_TASK` to BaseComponent
- Applied @task to: BigQueryExtract, GCSExtract, BQTransform, WriteFeatures, ReadFeatures
- ML components (TrainModel, EvaluateModel, RegisterModel, DeployModel) inherit ML_TASK default
- tests/components/test_decorators.py — 10 tests

### Task 2.2 — Unified Components
- Created `gcp_ml_framework/components/operators/` package
- Created `BQQuery(BaseComponent)` — absorbs BQQueryTask: sql/sql_file validation, resolve_sql(), resolve_destination(), render_operator(), execute() via BigQuery SDK
- Created `Email(BaseComponent)` — absorbs EmailTask: to/subject/body validation, resolve_subject/body(), render_operator(), execute() logs warning
- Template resolution via _resolve_templates() ported from dag/tasks/bq_query.py
- tests/components/test_bq_query.py — 8 tests
- tests/components/test_email.py — 5 tests

### Task 2.3 — Unified Pipeline Builder
- Added `Pipeline` class extending PipelineBuilder with `.add()` method
- `.add()` auto-infers stage from component class name via _STAGE_MAP_BY_NAME
- `.add()` reads _task_type from component's ClassVar (set by decorators)
- PipelineStep gained `task_type: TaskType` field
- PipelineDefinition gained `has_mixed_types` and `ml_task_groups` properties
- Updated `gcp_ml_framework/__init__.py` to export Pipeline, task, ml_task, TaskType
- PipelineBuilder._add() also populates task_type for backward compat
- tests/pipeline/test_unified_builder.py — 12 tests (renamed from 13 after dedup)

### Task 2.4 — SmartCompiler
- Created `gcp_ml_framework/pipeline/smart_compiler.py`
- _group_steps() splits steps at task_type boundaries into _StepGroup dataclasses
- Pure @task → DAG only, no YAML
- Pure @ml_task → KFP YAML (via PipelineCompiler) + DAG with RunPipelineJobOperator
- Mixed → DAG with native operators + RunPipelineJobOperator(s) for ML groups
- CompilationResult dataclass: dag_path + yaml_paths
- Updated cmd_compile.py to use SmartCompiler instead of PipelineCompiler + auto_wrap_pipeline_dag
- tests/pipeline/test_smart_compiler.py — 9 tests

### Task 2.5 — LocalRunner
- Created `gcp_ml_framework/pipeline/local_runner.py`
- Executes all steps in-process regardless of task_type
- Reuses PipelineCompiler._build_context_params() and _build_derived_params() for param merging
- Threads cross-step outputs (last_model_output, last_dataset_output)
- Updated cmd_run.py: added --local flag, _run_local() function
- tests/pipeline/test_local_runner.py — 5 tests

### Task 2.6 — Migrate training_pipeline
- Updated `pipelines/training_pipeline/pipeline.py` to use `Pipeline` with `.add()`
- Import simplified from `gcp_ml_framework import Pipeline`

### Task 2.7 — Deprecate Old DAG System
- dag/builder.py: added deprecation docstring
- dag/factory.py: updated docstring, auto_dag_for_pipeline() delegates to SmartCompiler
- DAG tasks kept functional for backward compat (later deleted in Phase 2.5)

---

## Phase 2.5: Deprecation Cleanup

**Completed:** 2026-03-20
**Verification:** 127 unit tests passing, 0 ruff errors, 0 Pydantic warnings, 0 old DAG references

### What was cleaned up
The old DAG system (`gcp_ml_framework/dag/`) was deprecated in Phase 2 but kept for backward compatibility. Since nothing is in production and zero dag.py pipelines exist, Phase 2.5 deleted it entirely.

### Deletions
- Deleted `gcp_ml_framework/dag/` — 11 files (builder.py, compiler.py, factory.py, operators.py, runner.py, tasks/{__init__,base,bq_query,email,vertex_pipeline}.py)
- Deleted `tests/dag/` — 2 files (__init__.py, test_compiler.py containing 4 tests)

### CLI Simplifications
- `cmd_compile.py`: Removed `_compile_dag()`, `_compile_embedded_vertex_pipelines()`, `_load_dag()`, dag.py detection
- `cmd_deploy.py`: Removed dag.py path in `_resolve_match_names()`, simplified to `{name}` set
- `cmd_run.py`: Removed `--composer` flag, `_run_composer()` function, dag.py error message in `_run_vertex()`
- `cmd_init.py`: Removed `--dag` flag, `_DAG_PY`/`_DAG_CONFIG_YAML`/`_DAG_EXTRACT_SQL`/`_DAG_TRANSFORM_SQL` templates

### Template Update
- Updated `_PIPELINE_PY` template from old `PipelineBuilder.ingest()` chain to new `Pipeline.add()` API

### Code Quality Fixes
- Fixed 4 Pydantic deprecation warnings: `instance.model_fields` → `type(instance).model_fields` in:
  - `pipeline/local_runner.py` (3 occurrences)
  - `pipeline/compiler.py` (1 occurrence)
  - `components/base.py` (1 occurrence)
- Fixed all ruff errors across entire codebase:
  - Phase 1/2 files: E501 in cmd_context.py, cmd_deploy.py, cmd_run.py, base.py, local_runner.py; I001 in compiler.py, base.py; UP032 in cmd_init.py
  - Pre-existing files: E501 in cmd_teardown.py, context.py, runner.py, feature_store.py; F401 in bq_transform.py, vertex.py, feature_store.py; I001 in client.py, context.py, feature_store.py; N806 in evaluate.py

### Replacement Tests
- Added 3 tests to `tests/pipeline/test_smart_compiler.py`:
  - `test_generated_dag_is_valid_python` — exec() on SmartCompiler output doesn't raise
  - `test_dev_schedule_is_none` — DEV environment produces schedule=None
  - `test_non_dev_schedule_preserved` — non-DEV uses declared schedule
- Net: 128 → 127 tests (-4 old DAG tests + 3 new SmartCompiler tests)

### Config Simplification (post-Phase 2.5)
- **Removed `framework.yaml`** — all config now comes from env vars via `.env`
- `load_config()` no longer accepts `framework_yaml` parameter
- CLI `--config`/`-c` flag removed from all commands
- `gml init project` scaffolds `.env` instead of `framework.yaml`
- `bootstrap.sh` reads env vars instead of grepping YAML
- Resolution order: `defaults → pipeline/config.yaml → env vars → CLI flags`

### Deferred Verifications (completed in Phase 2.5)
- Fixed `.env` to use `GML_*` prefixed variable names (was using old `GCP_*` names)
- Updated `framework.yaml` with real GCP project values (had placeholder `YOUR_*` values)
- `UV_ENV_FILE=.env uv run -- gml context show` — shows environment=dev, namespace=mlplatform-second-run-version-1, project=<your-gcp-project>
- `UV_ENV_FILE=.env uv run -- gml compile training_pipeline` — produces valid KFP YAML (5356 bytes) + Airflow DAG (1819 bytes) with correct project ID, region, schedule=None for DEV, correct service account

### Final Verification
```
uv run -- pytest tests/ -m unit -v                    → 127 passed, 0.39s
uv run -- ruff check gcp_ml_framework/ tests/         → All checks passed!
uv run -- pytest tests/ -m unit -W error::DeprecationWarning → 127 passed, 0 warnings
grep -r "from gcp_ml_framework.dag" gcp_ml_framework/ → no matches
UV_ENV_FILE=.env uv run -- gml context show            → environment: dev, correct GCP config
UV_ENV_FILE=.env uv run -- gml compile training_pipeline → valid YAML + DAG generated
```

---

## Phase 3: Cloud Build + Docker

**Completed:** 2026-03-20
**Verification:** 132 unit tests passing (5 new build tests), ruff clean, 2-layer Docker hierarchy
**REQS addressed:** 18.0 (Docker Cloud Build), 18.0b (Simplify Docker Hierarchy)
**ADRs:** ADR-005 (Cloud Build for All Builds), ADR-011 (Docker Image Hierarchy Simplification)

### Task 3.1 — cloudbuild.yaml + .gcloudignore
- Created `cloudbuild.yaml` — 4-step Cloud Build config:
  - Step 0: Pull cached base-python:latest (|| true for first build)
  - Step 1: Build base-python with --cache-from
  - Step 2: Pull cached pipeline:latest (|| true for first build)
  - Step 3: Build pipeline image with --cache-from + BASE_IMAGE build-arg
- Machine type: E2_HIGHCPU_8
- Substitutions: _TAG, _PIPELINE, _AR_REPO (set by `gml build`)
- Images section pushes both :tag and :latest for cache strategy
- Created `.gcloudignore` — excludes .terraform/, *.tfstate*, .env, *.pem, *.key, credentials, secrets, caches, tests/, docs/

### Task 3.2 — Docker Hierarchy Simplification (ADR-011)
- Created `docker/pipeline/Dockerfile` — unified from base-ml + component-base:
  - Layer 1 (cached): pyproject.toml + uv.lock → `uv sync --frozen --extra trainer --extra components --no-install-project`
  - Layer 2 (changes often): source code COPY → `uv sync --frozen --extra trainer --extra components`
  - Removed BuildKit `--mount=type=cache` (useless on Cloud Build ephemeral VMs)
  - Added `--frozen` for reproducibility
- Kept `docker/base/base-python/Dockerfile` unchanged (no BuildKit mounts, works on Cloud Build)
- Deleted `docker/base/component-base/Dockerfile`
- Deleted `docker/base/base-ml/Dockerfile`

### Task 3.3 — `gml build` CLI Command (ADR-005)
- Created `gcp_ml_framework/cli/cmd_build.py`:
  - `build()` — Typer command: `gml build [name | --all] [--timeout]`
  - `build_command()` — pure function returning `list[str]` of gcloud args (fully testable)
  - `_submit_build()` — executes subprocess, handles exit codes
  - Uses `naming.image_tag()` and `naming.artifact_registry_repo()` for tag/repo derivation
  - Uses `_slugify()` for pipeline name → pipeline slug (underscores → hyphens)
- Registered in `cli/main.py` as `app.command("build")(build)`

### Task 3.4 — Supporting Changes
- Updated `cmd_deploy.py` line 146: error message now says `gml build` instead of `docker_build.sh`
- Updated `scripts/docker_build.sh` line 117: references `docker/pipeline/Dockerfile` instead of `base-ml`

### Task 3.5 — Tests (TDD)
- Added `TestBuildCommand` class to `tests/cli/test_commands.py` — 5 tests:
  - `test_build_command_exists` — "build" in app.registered_commands
  - `test_build_module_imports` — cmd_build.build is callable
  - `test_build_command_constructs_gcloud_args` — verifies gcloud, submit, --config, _PIPELINE=, _TAG=
  - `test_build_command_uses_correct_pipeline_slug` — "training-pipeline" in joined args
  - `test_build_command_timeout` — custom timeout passed through

### Task 3.6 — Terraform IAM (Deferred)
- Initially added Cloud Build SA IAM bindings to `terraform/envs/dev/main.tf`
- **Reverted:** Sandbox uses pre-existing SAs; dev Terraform already skips IAM module. Cloud Build default SA likely has sufficient permissions. Verify at first `gml build` in Phase 4.

### Final Verification
```
uv run -- pytest tests/ -m unit -v                    → 132 passed, 0.41s
uv run -- ruff check gcp_ml_framework/ tests/         → All checks passed!
UV_ENV_FILE=.env uv run -- gml --help                  → "build" command visible
UV_ENV_FILE=.env uv run -- gml build --help            → shows name, --all, --timeout options
ls docker/base/base-python/ docker/pipeline/           → both exist
ls docker/base/base-ml/ docker/base/component-base/    → both deleted
grep -r "component-base\|base-ml" gcp_ml_framework/   → no matches
python -c "import yaml; yaml.safe_load(open('cloudbuild.yaml'))" → valid YAML
```

---

## Phase 4: Training Pipeline E2E on GCP

**Completed:** 2026-03-21
**Verification:** 146 unit tests passing (14 new), ruff clean, full E2E chain verified
**REQS addressed:** E2E pipeline execution proof, dataset field fix, Composer-as-orchestrator enforcement

### Task 4.1-4.2 — Environment + Data
- Verified `.env` has correct GCP config (project, region, SA, Composer details)
- Seeded BigQuery data via `seed_bq.sh` (50 rows in `{namespace}.housing_data_table`)

### Task 4.3-4.4 — Local Execution
- Fixed critical SQL bug: hardcoded `demo_housing_data` → `{dataset}` template
- Added `dataset: str = ""` to BaseComponent (universal param, populated by `_build_context_params`)
- Updated `train_house_model.py` to format SQL with `self.dataset`
- `gml run training_pipeline --local` completes: model uploaded to GCS

### Task 4.5 — Compile
- `gml compile training_pipeline` produces valid YAML + Airflow DAG
- Correct image URIs, service account, pipeline root paths

### Task 4.6 — Build
- `gml build training_pipeline` succeeds via Cloud Build (1m55s)
- Used pipeline SA (`--service-account`) for AR Writer permissions
- Replaced `images:` section with explicit `docker push` steps (infrastructure SA lacks AR Writer)
- Added `logging: CLOUD_LOGGING_ONLY` (custom SA lacks default logs bucket access)

### Task 4.7 — Deploy
- `gml deploy training_pipeline` uploads DAG to Composer + YAML to GCS

### Task 4.8 — Remove --vertex, Add Composer Trigger
- Removed `--vertex`, `--sync`, `--no-cache` flags from `cmd_run.py`
- Removed `_run_vertex()` function entirely
- Added `composer_trigger_command()` — pure function returning gcloud args (testable)
- Added `_run_composer()` — triggers DAG via `gcloud composer environments run`
- Default behavior: `gml run pipeline` triggers Composer DAG (no flags needed)
- `gml run pipeline --local` stays as-is
- `VertexRunner` stays as internal utility (used by DAG's `RunPipelineJobOperator`)

### Task 4.9 — Trigger Pipeline via Composer
- `gml run training_pipeline` successfully triggered DAG `mlplatform_second_run_version___training_pipeline`
- DAG state: running → RunPipelineJobOperator submits to Vertex AI

### Task 4.10 — Tests
- 4 unit tests in `tests/training_pipeline/test_steps.py` (instantiation, dataset field, SQL template, CLI help)
- 2 e2e tests in `tests/training_pipeline/test_e2e.py` (compile YAML, local run)
- 10 unit tests in `tests/cli/test_commands.py` TestRunCommand class:
  - run command exists, module imports, no --vertex/--sync/--no-cache flags
  - composer_trigger_command: gcloud args, DAG ID, env name, region+project
  - --local flag preserved

### Key Decisions
- **Composer is sole orchestrator**: No direct Vertex AI submission from CLI. `--vertex` was an architectural shortcut that bypassed Composer, skipped `@task` steps in mixed pipelines, and created false E2E validation.
- **Cloud Build SA**: Sandbox can't modify IAM. Used pipeline SA (has AR Writer) via `--service-account` flag. Explicit `docker push` steps instead of `images:` section.
- **Dataset as universal param**: `dataset` on BaseComponent follows the same pattern as `project`, `region`, `branch`. Enables branch-isolated BQ queries.

### Final Verification
```
uv run -- pytest tests/ -m unit -v                    → 146 passed, 0.60s
uv run -- ruff check gcp_ml_framework/ tests/         → All checks passed!
UV_ENV_FILE=.env uv run -- gml run --help              → --local, --all, --run-date (no --vertex)
UV_ENV_FILE=.env uv run -- gml run training_pipeline   → DAG triggered, state: running
```

---

## Phase 4.5: Phases 1-4 Fixes

**Completed:** 2026-03-21
**Verification:** 176 unit tests passing (30 new), ruff clean, both pipelines compile and run E2E on GCP
**REQS addressed:** 11.0 (Pipeline API collapse), execute()→run() lifecycle, render_operator() consistency, dead code cleanup

### Task 4.5.1 — Add Explicit @ml_task Decorators
- Added `@ml_task` to TrainModel, EvaluateModel, RegisterModel, DeployModel
- Previously relied on BaseComponent default — now explicit per decorator architecture

### Task 4.5.2 — Fix execute()→run() Lifecycle
- EvaluateModel, RegisterModel, DeployModel: moved execute() body into run(), execute() calls self.run()
- Data scientist subclass pattern now works: override run() → custom code executes
- TrainModel already correct (no changes)

### Task 4.5.3 — Fix render_operator() Across @task Components
- BQTransform: added render_operator() → BigQueryInsertJobOperator
- Email: fixed signature to accept pipeline_dir kwarg
- WriteFeatures: added render_operator() → PythonOperator

### Task 4.5.4 — Fix SmartCompiler No-Op Fallback
- Replaced `lambda: None` with NotImplementedError for @task components without render_operator()

### Task 4.5.5 — Remove Redundant & Broken Components
- Deleted: ReadFeatures, BigQueryExtract, GCSExtract (classes + utility files)
- Deleted: utils/sql_compat.py, utils/logging.py (orphaned dead code)
- Deleted: orphaned run_read_features() from utils/feature_store.py
- Cleaned all references from tests, docstrings, stage maps

### Task 4.5.6 — Collapse Pipeline API (REQS 11.0)
- Deleted PipelineBuilder class with all 8 named methods
- Removed stage field from PipelineStep, deleted _STAGE_MAP_BY_NAME and _infer_stage()
- Pipeline is standalone with only .add() and .build()
- Added component import facade: `from gcp_ml_framework.components import BQQuery, TrainModel`

### Task 4.5.7 — Create verification_pipeline
- Mixed @task + @ml_task pipeline: BQQuery → BQTransform → TrainVerifyModelStep
- Proves SmartCompiler correctly groups [TASK, TASK] + [ML_TASK]

### Task 4.5.8 — Tests for verification_pipeline
- 10 tests: definition (step count, names, mixed types, task types) + compilation (compiles, YAML, BQ operators, Vertex operator, dependencies, valid Python)

### Task 4.5.9 — Fix CLI Bugs
- cmd_deploy.py: fixed error handling (was swallowing compilation failures)
- cmd_init.py: fixed templates to use real CLI commands, Python 3.12
- Extracted shared load_pipeline() to _helpers.py

### Task 4.5.10 — Full Verification + Audit
- 176 tests passing, ruff clean
- Both pipelines compile: training_pipeline + verification_pipeline
- Generated DAGs: 2 BigQueryInsertJobOperators + RunPipelineJobOperator
- Zero dead code references
- Fixed 2 runtime bugs found during E2E audit:
  - BQQuery.execute() now resolves {bq_dataset} templates + sets destination table
  - run_bq_transform() guards empty output_uri_path
- Both pipelines run successfully on real GCP (local + Composer triggered)
- Security audit: all sensitive strings scrubbed from tracked files

### Final Verification
```
uv run -- pytest tests/ -v                            → 176 passed
uv run -- ruff check gcp_ml_framework/ tests/         → All checks passed!
UV_ENV_FILE=.env uv run -- gml compile --all           → 2 YAML + 2 DAGs
UV_ENV_FILE=.env uv run -- gml build training_pipeline → SUCCESS (Cloud Build)
UV_ENV_FILE=.env uv run -- gml build verification_pipeline → SUCCESS (Cloud Build)
UV_ENV_FILE=.env uv run -- gml deploy --all            → DAGs + YAML uploaded
UV_ENV_FILE=.env uv run -- gml run training_pipeline   → Composer DAG triggered
UV_ENV_FILE=.env uv run -- gml run verification_pipeline → Composer DAG triggered
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local → BQ + train + GCS ✓
UV_ENV_FILE=.env uv run -- gml run verification_pipeline --local → 3 steps on real GCP ✓
```

---

## Phase 5: Complete ML Lifecycle — Training, Evaluation, Deployment & Monitoring

**Completed:** 2026-03-21
**Verification:** 210 unit tests passing, ruff clean, both pipelines compile and run E2E
**REQS addressed:** Full 6-step ML lifecycle, experiment tracking (ADR-007), model monitoring
**ADRs:** ADR-007 (Experiment Tracking)

### What was built
- Full 6-step pipelines: BQQuery → BQTransform → Train → Evaluate → Register → Deploy
- Experiment tracking in TrainModel.execute() (params) and EvaluateModel.execute() (metrics)
- Smart model resolution in run_deploy(): `projects/` URI → reuse registered model, `gs://` → upload
- Regression metrics (rmse, mae, r2) alongside existing classification in run_evaluate()
- Model monitoring fields on DeployModel (enable_monitoring, alert_email, thresholds)
- @task→@ml_task data bridging in SmartCompiler via RunPipelineJobOperator parameter_values
- Mixed execution test pipeline (@task/@ml_task/@task/@ml_task pattern)
- BQQuery output tracking (writes destination_table to output_uri_path)

### Key decisions
- **Evaluation step subclasses**: HouseEvaluateStep and EvaluateVerifyStep override run() for regression
- **Cross-step wiring**: RegisterModel output → last_model_output (not last_dataset_output) → DeployModel receives resource_name → smart resolution skips re-upload
- **Data bridging**: SmartCompiler tracks last_dataset_output across ALL step groups, passes as parameter_values to RunPipelineJobOperator at @task→@ml_task boundaries

### Final Verification
```
uv run -- pytest tests/ -m unit -v                          → 210 passed
uv run -- ruff check gcp_ml_framework/ tests/               → All checks passed!
UV_ENV_FILE=.env uv run -- gml compile --all                 → 2 YAML + 2 DAGs (6-step pipelines)
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local → 6 steps complete
UV_ENV_FILE=.env uv run -- gml run verification_pipeline --local → 6 steps complete
```

---

## Phase 5.5: Dedicated Serving Image (CPR)

**Completed:** 2026-03-21
**Verification:** 226 unit tests passing, ruff clean, serving images built and deployed to AR
**Trigger:** `ModuleNotFoundError: No module named 'second_run'` in Vertex AI serving logs

### Problem
Pre-built `sklearn-cpu.1-3:latest` serving container could not unpickle `HousePredictionModel` because it lacks the `second_run` package. Models registered successfully but failed to serve predictions.

### Solution
Built a dedicated lightweight serving Docker image alongside the pipeline image:
```
Docker hierarchy:
  base-python:tag
    ├── {pipeline}:tag              (training — unchanged)
    └── {pipeline}-serving:tag      (serving — slim, ~200MB)
```

### What was built
- `gcp_ml_framework/serving/handler.py` — Generic HTTP prediction server implementing Vertex AI CPR protocol
- `docker/serving/Dockerfile` — Slim serving image (only runtime deps + second_run/ + serving/)
- `cloudbuild.yaml` Steps 6-8 — Build and push `{pipeline}-serving` images
- `compiler.py` — Auto-defaults RegisterModel/DeployModel to serving image
- `register.py` + `vertex.py` — CPR routes for custom containers (predict/health routes, command, ports)
- `scripts/docker_build.sh` — Added serving image build
- 16 new tests (handler + CPR assertions across compiler, register, vertex)

### Key decisions
- **stdlib only**: Uses `http.server.HTTPServer` — no Flask/FastAPI dependency in serving image
- **Pre-built detection**: If serving_container_image starts with `us-docker.pkg.dev/vertex-ai/`, skip CPR kwargs (those are Vertex AI's pre-built containers with their own protocol)
- **Generic handler**: Works with any model that has `predict(pd.DataFrame)` method

### Final Verification
```
uv run -- pytest tests/ -m unit -v                          → 226 passed
uv run -- ruff check gcp_ml_framework/ tests/               → All checks passed!
UV_ENV_FILE=.env uv run -- gml compile --all                 → YAML uses serving image, not sklearn
UV_ENV_FILE=.env uv run -- gml build training_pipeline       → Pipeline + serving images built
UV_ENV_FILE=.env uv run -- gml build verification_pipeline   → Pipeline + serving images built
UV_ENV_FILE=.env uv run -- gml deploy --all                  → All 4 images verified, DAGs uploaded
UV_ENV_FILE=.env uv run -- gml run training_pipeline         → Composer DAG triggered
UV_ENV_FILE=.env uv run -- gml run verification_pipeline     → Composer DAG triggered
```
