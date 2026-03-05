# Next Steps — Implementation Guide

> Reference: `docs/planning/project_guideline.md` (the source of truth for design decisions)
> Approach: TDD — write tests first, then implement
> Each phase has a Definition of Done and verification steps

---

## Phase 1: Clean Foundation

**Goal**: Remove dead code, fix broken things, restructure CLI, update core interfaces. After this phase, the framework has the correct contracts for everything built on top.

---

### 1.1 Remove Dead Code

#### 1.1a Remove `as_airflow_operator()` from BaseComponent

**File**: `gcp_ml_framework/components/base.py`

**Current state** (lines 69-82): `BaseComponent` has an `as_airflow_operator()` method that wraps `local_run()` in a `PythonOperator`. This is dead code — the DAG compiler generates Airflow operators directly. No component's `as_airflow_operator()` is ever called.

**Action**:
1. Delete the `as_airflow_operator()` method (lines 69-82)
2. Remove the docstring reference to `as_airflow_operator()` (line 8)
3. Remove `from collections.abc import Callable` if unused after cleanup

**Tests**: Run `uv run pytest tests/unit/ -v` — all 167 existing tests must still pass.

**Verify**: `grep -r "as_airflow_operator" gcp_ml_framework/components/` should return zero hits (except in `dag/tasks/` which is a different interface on `BaseTask`).

#### 1.1b Remove PandasTransform

**File**: `gcp_ml_framework/components/transformation/bq_transform.py`

**Current state**: `PandasTransform` is defined in this file (or a separate file). It raises `NotImplementedError` on Vertex — violates the framework contract.

**Action**:
1. If `PandasTransform` is in `bq_transform.py`, remove the class definition
2. If in its own file, delete the file
3. Remove any imports of `PandasTransform` from `__init__.py` files
4. Search entire codebase: `grep -r "PandasTransform" .` — remove all references

**Tests**: Existing tests must still pass.

#### 1.1c Remove `composer_environment_name()` and `gcs_dag_sync_path()` from naming.py

**File**: `gcp_ml_framework/naming.py`

**Current state**:
- Line 188-189: `composer_environment_name()` returns `{namespace}-composer` — fabricated name (real Composer envs have random suffixes)
- Lines 115-117: `gcs_dag_sync_path()` returns `gs://{namespace}-composer/dags/{filename}` — fabricated bucket path

**Action**:
1. Delete `composer_environment_name()` method (line 188-189)
2. Delete `gcs_dag_sync_path()` method (lines 115-117)
3. Search codebase for callers: `grep -r "composer_environment_name\|gcs_dag_sync_path" .` — update or remove all callers (found in `cmd_deploy.py` lines 53-57)

**Tests to write first** (`tests/unit/test_naming.py`):
```python
def test_naming_has_no_composer_methods(naming_dev):
    """Verify fabricated Composer methods are removed."""
    assert not hasattr(naming_dev, "composer_environment_name")
    assert not hasattr(naming_dev, "gcs_dag_sync_path")
```

**Verify**: `uv run pytest tests/unit/test_naming.py -v` passes.

#### 1.1d Update default machine types

**File**: `gcp_ml_framework/components/base.py`

**Current state** (line 30): `ComponentConfig.machine_type` defaults to `"n1-standard-4"`.

**Action**: Change default to `"n2-standard-4"`.

**File**: `gcp_ml_framework/components/ml/train.py`

**Current state** (line 32): `machine_type: str = "n1-standard-4"`.

**Action**: Change to `"n2-standard-4"`.

---

### 1.2 Fix Broken Things

#### 1.2a Fix `EvaluateModel.local_run()`

**File**: `gcp_ml_framework/components/ml/evaluate.py`

**Current state** (lines 109-130): `local_run()` returns `random.uniform(0.75, 0.95)` — completely synthetic metrics. Misleading to data scientists.

**Action**:
1. Change `local_run()` to attempt loading a real model from `model_path` (if provided) and computing real metrics against seed data
2. If no model_path or no valid model is found, clearly log `"[local] No model found — using placeholder metrics"` and return fixed placeholder values (not random) — e.g., `{"auc": 0.50, "f1": 0.50}` with a warning
3. Remove `import random`

**Tests to write first** (`tests/unit/test_components.py`):
```python
def test_evaluate_local_run_no_random():
    """local_run must not use random — results should be deterministic."""
    from gcp_ml_framework.components.ml.evaluate import EvaluateModel
    eval1 = EvaluateModel(metrics=["auc"], gate={})
    result1 = eval1.local_run(context_dev)
    result2 = eval1.local_run(context_dev)
    assert result1 == result2  # deterministic, not random
```

**Verify**: `uv run pytest tests/unit/test_components.py::test_evaluate_local_run_no_random -v`

#### 1.2b Fix `utils/bq.py` — exception handling

**File**: `gcp_ml_framework/utils/bq.py`

**Current state** (line 25): `except Exception: return False` — catches everything including permission errors, network errors, etc.

**Action**: Change to catch only `google.cloud.exceptions.NotFound`:
```python
from google.api_core.exceptions import NotFound

try:
    client.get_table(f"{project}.{dataset}.{table}")
    return True
except NotFound:
    return False
```

**Tests to write first** (`tests/unit/test_utils_bq.py`):
```python
def test_table_exists_raises_on_permission_error():
    """table_exists should NOT swallow PermissionDenied."""
    # Mock client.get_table to raise PermissionDenied
    # Assert PermissionDenied propagates (not caught)
```

#### 1.2c Add `composer_dags_path` to config

**File**: `gcp_ml_framework/config.py`

**Current state**: `GCPConfig` has `composer_env: str = ""` which is empty and unused.

**Action**:
1. Replace `composer_env` with `composer_dags_path: dict[str, str] = {}` in `GCPConfig` — keys are `dev`, `staging`, `prod`
2. Add a method or property that returns the correct path based on current `git_state`
3. Update `framework.yaml` to use the new field name

**File**: `framework.yaml`

**Action**: Replace `composer_env:` with:
```yaml
  composer_dags_path:
    dev: ""    # Fill in after Terraform provisions Composer
    staging: ""
    prod: ""
```

**Tests to write first** (`tests/unit/test_config.py`):
```python
def test_composer_dags_path_from_config():
    """Config should load composer_dags_path per environment."""
    # Test that loading config with composer_dags_path works
    # Test that the correct path is returned for DEV/STAGING/PROD
```

---

### 1.3 Restructure CLI

#### 1.3a Create `gml compile` command

**New file**: `gcp_ml_framework/cli/cmd_compile.py`

**Behavior**:
- `gml compile <name>` — compile one pipeline/DAG
- `gml compile --all` — compile everything
- No args and no `--all` → error with helpful message

**What compile does**:
1. Discover the pipeline directory (`pipelines/{name}/`)
2. Detect `pipeline.py` or `dag.py` (error if both exist, error if neither)
3. If `pipeline.py`: compile to KFP YAML + auto-wrap in DAG file
4. If `dag.py`: compile to DAG file + compile any embedded VertexPipelineTasks to KFP YAML
5. Output: `compiled_pipelines/*.yaml` and `dags/*.py`

**Implementation**:
1. Extract `_run_compile()` logic from `cmd_run.py`
2. Extend to handle `dag.py` files (not just `pipeline.py`)
3. Add `--all` and single-name support
4. Register in `main.py`: `app.command("compile")(compile_cmd)`

**Remove from cmd_run.py**: Delete the `--compile-only` flag and `_run_compile()` function. `gml run` should only have `--local` and `--vertex` modes.

**Tests to write first** (`tests/unit/test_cli.py`):
```python
def test_compile_single_pipeline(tmp_path):
    """gml compile <name> generates KFP YAML + DAG file."""

def test_compile_all(tmp_path):
    """gml compile --all compiles all pipelines."""

def test_compile_rejects_both_pipeline_and_dag(tmp_path):
    """Error if pipeline dir has both pipeline.py and dag.py."""

def test_compile_rejects_empty_dir(tmp_path):
    """Error if pipeline dir has neither pipeline.py nor dag.py."""
```

#### 1.3b Unify `gml deploy`

**File**: `gcp_ml_framework/cli/cmd_deploy.py`

**Current state**: Two subcommands `deploy dags` and `deploy features`. Needs to be unified.

**New behavior**:
- `gml deploy <name>` — deploy one pipeline (its DAG file + pipeline YAML)
- `gml deploy --all` — deploy everything (all DAGs, all pipeline YAMLs, all feature schemas)
- `gml deploy --all --dry-run` — preview
- No subcommands. Single command.

**Action**:
1. Rewrite `cmd_deploy.py` as a single command (not a Typer sub-app)
2. Internally calls `gml compile` first (if not already compiled)
3. Uploads DAG files to Composer GCS bucket (using `composer_dags_path` from config)
4. Uploads compiled pipeline YAMLs to GCS (`gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml`)
5. Deploys feature schemas
6. Register in `main.py`: `app.command("deploy")(deploy)` (not `app.add_typer`)

**Tests to write first**:
```python
def test_deploy_single_pipeline_dry_run(tmp_path):
    """gml deploy <name> --dry-run shows what would be deployed."""

def test_deploy_all_dry_run(tmp_path):
    """gml deploy --all --dry-run lists all artifacts."""
```

#### 1.3c Remove `gml promote`

**File**: `gcp_ml_framework/cli/cmd_promote.py`

**Action**:
1. Delete `cmd_promote.py`
2. Remove from `main.py`: delete the `from ... import promote_app` line and `app.add_typer(promote_app, ...)` line

**Verify**: `gml --help` should NOT show `promote` as a command.

#### 1.3d Update `main.py` registrations

**File**: `gcp_ml_framework/cli/main.py`

After all CLI changes, `main.py` should register:
```python
app.add_typer(init_app, name="init")
app.add_typer(context_app, name="context")
app.command("run")(run)
app.command("compile")(compile_cmd)
app.command("deploy")(deploy)
app.add_typer(teardown_app, name="teardown")
```

---

### 1.4 Update Core Interfaces

#### 1.4a Add `sql_file` support to BQQueryTask

**File**: `gcp_ml_framework/dag/tasks/bq_query.py`

**Current state**: Only supports inline `sql: str`. No way to reference external SQL files.

**Action**:
1. Add `sql_file: str | None = None` field
2. `sql` and `sql_file` are mutually exclusive — validate in `validate()`
3. Add `resolve_sql_content(pipeline_dir: Path)` method that loads from file if `sql_file` is set
4. The compiler calls this method, passing the pipeline directory path

**Tests to write first** (`tests/unit/test_dag_tasks.py`):
```python
def test_bq_query_sql_file_and_inline_exclusive():
    """Cannot specify both sql and sql_file."""

def test_bq_query_loads_sql_from_file(tmp_path):
    """sql_file loads SQL content from the file."""

def test_bq_query_sql_file_template_resolution(tmp_path):
    """Template macros in loaded SQL are resolved."""
```

#### 1.4b Rewrite VertexPipelineTask to accept PipelineDefinition

**File**: `gcp_ml_framework/dag/tasks/vertex_pipeline.py`

**Current state**: Takes `pipeline_name: str` and tries to import `pipeline.py` at Airflow parse time. This makes the generated DAG NOT self-contained (imports `gcp_ml_framework`).

**Action — this is the most critical change in Phase 1**:
1. Change the dataclass to accept a `PipelineDefinition` object:
   ```python
   pipeline: PipelineDefinition | None = None   # The builder output
   pipeline_name: str = ""                       # Fallback: just a name for the compiled YAML
   ```
2. Remove all `importlib` logic from `as_airflow_operator()`
3. The **compiler** (not the task) handles generating the Airflow operator code

**File**: `gcp_ml_framework/dag/compiler.py`

**Current state** (lines 171-207): `_render_vertex_pipeline()` generates code that imports `gcp_ml_framework` at Airflow runtime. This violates the "self-contained DAGs" principle.

**Action**: Rewrite `_render_vertex_pipeline()` to generate a `CreatePipelineJobOperator` (from `airflow.providers.google.cloud.operators.vertex_ai.pipeline_job`) that references the compiled YAML at its GCS path:
```python
def _render_vertex_pipeline(self, name, task, context):
    imports = {
        "from airflow.providers.google.cloud.operators.vertex_ai.pipeline_job import CreatePipelineJobOperator",
    }
    # Compile the PipelineDefinition to YAML if we have it
    pipeline_name = task.pipeline.name if task.pipeline else task.pipeline_name
    template_path = f"gs://{context.naming.gcs_bucket}/{context.naming.branch}/pipelines/{pipeline_name}/pipeline.yaml"
    pipeline_root = f"gs://{context.naming.gcs_bucket}/{context.naming.branch}/pipeline_runs/{pipeline_name}/"

    code = f"""{name} = CreatePipelineJobOperator(
    task_id="{name}",
    project_id="{context.gcp_project}",
    location="{context.region}",
    display_name="{pipeline_name}_{{{{ ds_nodash }}}}",
    template_path="{template_path}",
    pipeline_root="{pipeline_root}",
)"""
    return code, imports
```

**Tests to write first** (`tests/unit/test_dag_compiler.py`):
```python
def test_vertex_pipeline_renders_self_contained():
    """Generated DAG code must NOT import from gcp_ml_framework."""
    # Compile a DAG with VertexPipelineTask
    # Assert the rendered code does not contain "gcp_ml_framework"
    # Assert it uses CreatePipelineJobOperator

def test_vertex_pipeline_references_gcs_yaml():
    """Generated code must reference the compiled YAML at its GCS path."""
```

**This change also requires**: When `gml compile` encounters a DAG with VertexPipelineTasks, it must compile each embedded PipelineDefinition to a separate YAML file. Update the compile command to handle this.

#### 1.4c Update DAG compiler header

**File**: `gcp_ml_framework/dag/compiler.py`

**Current state** (line 69): Header says `Regenerate with: gml deploy dags`

**Action**: Change to `Regenerate with: gml compile`

---

### 1.5 Bump Dependencies

**File**: `pyproject.toml`

**Action**: Update dependency versions:
```
kfp>=2.15,<3
google-cloud-aiplatform>=1.136
google-cloud-bigquery>=3.25
google-cloud-storage>=2.18
google-cloud-secret-manager>=2.21
apache-airflow>=2.10
apache-airflow-providers-google>=20.0
pydantic>=2.9
pydantic-settings>=2.6
typer>=0.15
duckdb>=1.1
pyarrow>=18
pandas>=2.2
```

Run `uv lock` after updating.

**Verify**: `uv run pytest tests/unit/ -v` — all tests pass with new versions.

---

### Phase 1 Definition of Done

- [x] `grep -r "as_airflow_operator" gcp_ml_framework/components/` returns zero hits
- [x] `grep -r "PandasTransform" .` returns zero hits
- [x] `grep -r "composer_environment_name\|gcs_dag_sync_path" .` returns zero hits
- [x] `grep -r "n1-standard" gcp_ml_framework/` returns zero hits
- [x] `gml compile --help` works
- [x] `gml deploy --help` works (single command, no subcommands)
- [x] `gml promote` does not exist (`gml --help` shows no promote)
- [x] `gml run --help` does NOT show `--compile-only`
- [x] `EvaluateModel().local_run(ctx)` returns deterministic results (not random)
- [x] `uv run pytest tests/unit/ -v` — all tests pass (202 pass, old + 35 new)
- [x] Generated DAG files contain zero `gcp_ml_framework` imports (uses CreatePipelineJobOperator)

**Local verification**:
```bash
uv run pytest tests/unit/ -v
uv run gml compile --all
# Inspect dags/*.py — verify no gcp_ml_framework imports
grep "gcp_ml_framework" dags/*.py   # should return nothing
uv run gml --help                    # verify command list
```

---

## Phase 2: Three Use Cases + Docker Automation + Local DAG Runner

**Goal**: Build the three toy use cases, implement Docker auto-generation, and create the local DAG runner. After this phase, `gml run <name> --local` and `gml compile --all` work for all three use cases.

---

### 2.1 Docker Auto-Generation

#### 2.1a Create base Dockerfiles

**Create**: `docker/base/base-python/Dockerfile`
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && \
    rm -rf /var/lib/apt/lists/*
```

**Create**: `docker/base/base-ml/Dockerfile`
```dockerfile
FROM base-python:latest
RUN pip install --no-cache-dir \
    numpy pandas scikit-learn xgboost lightgbm pyarrow
```

These are the platform-owned base images. Data scientists never modify them.

#### 2.1b Create Docker auto-generation script

**Create**: `scripts/docker_build.sh`

This script is called by CI/CD. It:
1. Scans `pipelines/*/trainer/` for directories containing `train.py` + `requirements.txt`
2. If no `Dockerfile` exists in the trainer dir, auto-generates one using the base-ml image
3. Builds and tags the image

For now, this is a shell script. It will be called by CI/CD in Phase 6.

**Tests**: Verify the script generates valid Dockerfiles:
```bash
# Create a temp pipeline with trainer/train.py + requirements.txt
# Run the script
# Verify Dockerfile was generated
# Verify docker build succeeds (if Docker is available)
```

#### 2.1c Make `trainer_image` optional in TrainModel

**File**: `gcp_ml_framework/components/ml/train.py`

**Current state** (line 31): `trainer_image: str` — required field.

**Action**:
1. Change to `trainer_image: str = ""` (optional)
2. Add image resolution logic in `as_kfp_component()`: if `trainer_image` is empty, derive from the pipeline name passed via context
3. Add a `resolve_image_uri(pipeline_name: str, context: MLContext) -> str` method that constructs the full AR URI

**Tests to write first**:
```python
def test_train_model_auto_derives_image():
    """TrainModel with no trainer_image derives name from pipeline."""

def test_train_model_explicit_image_honored():
    """Explicit trainer_image overrides auto-derivation."""
```

---

### 2.2 Local DAG Runner

**Create**: `gcp_ml_framework/dag/runner.py`

This is the local execution engine for DAGBuilder-defined workflows. Referenced by `gml run <name> --local` when the pipeline has `dag.py`.

**Behavior** (per project_guideline.md Section 8.3):
1. Load seed data from `seeds/` into DuckDB
2. Compute topological order of all tasks
3. Execute tasks sequentially in topological order
4. Per task type:
   - `BQQueryTask` → run SQL via DuckDB (with `sql_compat` translation). Load `sql_file` from disk if specified.
   - `EmailTask` → print to console (recipients, subject, resolved body)
   - `VertexPipelineTask` → run the contained `PipelineDefinition` locally via the pipeline LocalRunner (recursive)
5. Simulated context: `{run_date}` → from `--run-date` flag or today

**Tests to write first** (`tests/unit/test_dag_runner.py`):
```python
def test_dag_runner_topological_order():
    """Tasks execute in valid topological order."""

def test_dag_runner_bq_query_via_duckdb():
    """BQQueryTask executes SQL against DuckDB with seed data."""

def test_dag_runner_email_prints_to_console(capsys):
    """EmailTask prints recipients and subject, does not send."""

def test_dag_runner_vertex_pipeline_runs_locally():
    """VertexPipelineTask runs contained PipelineDefinition via LocalRunner."""

def test_dag_runner_sql_file_loaded(tmp_path):
    """BQQueryTask with sql_file loads and executes the file contents."""
```

**Update `cmd_run.py`**: Modify `_run_local()` to detect `dag.py` vs `pipeline.py` and use the appropriate runner:
```python
if (pipeline_dir / "dag.py").exists():
    # Use DAG local runner
    from gcp_ml_framework.dag.runner import DAGLocalRunner
    dag_def = _load_dag(pipeline_dir)
    runner = DAGLocalRunner(ctx, seeds_dir=seeds_dir, pipeline_dir=pipeline_dir)
    runner.run(dag_def)
elif (pipeline_dir / "pipeline.py").exists():
    # Use pipeline local runner (existing)
    ...
```

---

### 2.3 Update Churn Prediction Use Case

**Directory**: `pipelines/example_churn/` (rename to `pipelines/churn_prediction/` if different)

**Changes**:
1. Remove explicit `trainer_image` from `TrainModel()` — let auto-resolution handle it
2. Change `machine_type` from n1 to n2 if present
3. Remove `trainer/Dockerfile` if it exists (platform auto-generates)
4. Keep `trainer/train.py` and add `trainer/requirements.txt` (extracted from Dockerfile)
5. Verify `gml compile churn_prediction` generates both KFP YAML and auto-wrapped DAG file
6. Verify `gml run churn_prediction --local` works end-to-end

**Tests**: `gml compile churn_prediction` succeeds and generates:
- `compiled_pipelines/churn_prediction.yaml`
- `dags/{namespace}__churn_prediction.py`

---

### 2.4 Create Sales Analytics Use Case

**Create**: `pipelines/sales_analytics/`

```
pipelines/sales_analytics/
├── dag.py                       # DAGBuilder with 8 tasks (non-linear)
├── sql/
│   ├── extract_orders.sql       # SELECT order_id, ... FROM {bq_dataset}.raw_orders WHERE order_date = '{run_date}'
│   ├── extract_inventory.sql
│   ├── extract_returns.sql
│   ├── agg_revenue.sql          # SELECT category, SUM(amount) ... GROUP BY ...
│   ├── check_stock.sql
│   ├── agg_refunds.sql
│   └── build_report.sql         # JOIN revenue, stock, refunds → daily_report
├── config.yaml                  # schedule, tags
└── seeds/
    ├── raw_orders.csv           # ~20 rows: order_id, customer_id, category, amount, region, order_date
    ├── raw_inventory.csv        # ~10 rows: item_id, category, stock_count, warehouse
    └── raw_returns.csv          # ~8 rows: return_id, order_id, reason, refund_amount, return_date
```

**DAG shape** (non-linear):
```
extract_orders ────→ agg_revenue ────→┐
extract_inventory ─→ check_stock ────→├→ build_report → notify
extract_returns ───→ agg_refunds ───→┘
```

**Tests**:
```python
def test_sales_analytics_compiles():
    """gml compile sales_analytics produces valid DAG file."""

def test_sales_analytics_dag_shape():
    """DAG has correct dependency graph (fan-out + fan-in)."""

def test_sales_analytics_local_run():
    """gml run sales_analytics --local executes all 8 tasks against seed data."""
```

---

### 2.5 Create Recommendation Engine Use Case

**Create**: `pipelines/recommendation_engine/`

```
pipelines/recommendation_engine/
├── dag.py                       # DAGBuilder with BQ task + 2 VertexPipelineTasks + email
├── sql/
│   ├── extract_interactions.sql
│   ├── user_features.sql
│   └── item_features.sql
├── trainer/
│   ├── train.py                 # Simple collaborative filtering (sklearn NMF or similar)
│   └── requirements.txt
├── config.yaml
└── seeds/
    └── raw_interactions.csv     # ~30 rows: user_id, item_id, interaction_type, ts
```

**Flow**: See project_guideline.md Section 6.3

**Tests**:
```python
def test_reco_engine_compiles():
    """gml compile recommendation_engine produces DAG file + 2 KFP YAMLs."""

def test_reco_engine_two_vertex_pipelines():
    """Compiled output includes reco_features.yaml and reco_training.yaml."""

def test_reco_engine_local_run():
    """gml run recommendation_engine --local runs DAG + both pipelines locally."""
```

---

### Phase 2 Definition of Done

- [x] `docker/base/base-python/Dockerfile` and `docker/base/base-ml/Dockerfile` exist
- [x] `scripts/docker_build.sh` auto-generates Dockerfiles for pipelines with `trainer/`
- [x] `TrainModel()` works without explicit `trainer_image`
- [x] `gml compile --all` compiles all 3 use cases without error
- [x] `gml run churn_prediction --local` completes successfully
- [x] `gml run sales_analytics --local` completes successfully (8 tasks, non-linear)
- [x] `gml run recommendation_engine --local` completes successfully (DAG + 2 Vertex pipelines)
- [x] All generated DAG files contain zero `gcp_ml_framework` imports
- [x] All new and existing tests pass: `uv run pytest tests/unit/ -v`

**Local verification**:
```bash
uv run pytest tests/unit/ -v
uv run gml compile --all
uv run gml run churn_prediction --local
uv run gml run sales_analytics --local
uv run gml run recommendation_engine --local
grep "gcp_ml_framework" dags/*.py   # should return nothing
ls compiled_pipelines/               # should have churn_prediction.yaml, reco_features.yaml, reco_training.yaml
ls dags/                             # should have 3 DAG files
```

---

## Phase 3: Feature Store + Model Management

**Goal**: Rewrite Feature Store for v2 BQ-native APIs. Add model versioning and experiment tracking. After this phase, Feature Store operations work correctly and models are properly versioned.

---

### 3.1 Rewrite Feature Store Client

**File**: `gcp_ml_framework/feature_store/client.py`

**Current state**: Uses v1 APIs. `ensure_feature_view()` is non-functional. `trigger_sync()` is a stub. `WriteFeatures` uses broken gRPC workaround.

**Action**: Full rewrite for v2 APIs:
1. `FeatureGroup` — registers a BQ table as a feature group (metadata only)
2. `Feature` — registers individual columns
3. `FeatureOnlineStore` — creates Bigtable-backed online serving
4. `FeatureView` — connects FeatureGroup to OnlineStore with sync schedule

**Tests to write first** (`tests/unit/test_feature_store_client.py`):
```python
def test_ensure_feature_group_creates_metadata():
    """ensure_feature_group registers a BQ table (mocked)."""

def test_ensure_feature_view_connects_to_online_store():
    """ensure_feature_view creates serving connection (mocked)."""
```

### 3.2 Simplify WriteFeatures Component

**File**: `gcp_ml_framework/components/feature_store/write_features.py`

**Action**: Replace the gRPC/LRO workaround with a simple metadata registration call. Since `BQTransform` already writes data to BQ, `WriteFeatures` just registers the table as a FeatureGroup.

### 3.3 Fix ReadFeatures Component

**File**: `gcp_ml_framework/components/feature_store/read_features.py`

**Action**:
- Offline (training): read from BQ table directly
- Online (inference): read from Feature Store serving API
- `local_run()`: read from local DuckDB table (not empty DataFrame)

### 3.4 Model Versioning

**File**: `gcp_ml_framework/components/ml/train.py`

**Action**: Change model output path from `latest/model.pkl` to `{pipeline_name}/{run_id}/model.pkl`. Register in Vertex AI Model Registry with metadata (commit SHA, hyperparameters).

### 3.5 Experiment Tracking

**File**: `gcp_ml_framework/components/ml/evaluate.py`

**Action**: Add `aiplatform.log_metrics()` in the KFP component to log computed metrics to Vertex AI Experiments.

---

### Phase 3 Definition of Done

- [ ] `feature_store/client.py` uses v2 APIs (FeatureGroup, FeatureView, FeatureOnlineStore)
- [ ] `WriteFeatures` is metadata-only (no gRPC, no LRO, no 10-minute wait)
- [ ] `ReadFeatures.local_run()` returns actual data from DuckDB (not empty DataFrame)
- [ ] `TrainModel` writes to versioned GCS paths (`{pipeline}/{run_id}/model.pkl`)
- [ ] `EvaluateModel` KFP component calls `aiplatform.log_metrics()`
- [ ] All tests pass: `uv run pytest tests/unit/ -v`

**GCP verification** (requires GCP access):
```bash
# Deploy feature schemas to dev
GML_ENV_OVERRIDE=DEV uv run gml deploy --all
# Check Vertex AI console → Feature Store → verify FeatureGroups created
```

---

## Phase 4: Infrastructure (Terraform)

**Goal**: Terraform modules for shared infrastructure. After this phase, running `terraform apply` provisions all required GCP resources.

---

### 4.1 Create Terraform Modules

**Create**:
```
terraform/
  modules/
    composer/main.tf           # google_composer_environment (Composer 3)
    composer/variables.tf
    composer/outputs.tf        # Output: composer_dags_path
    artifact_registry/main.tf  # google_artifact_registry_repository
    iam/main.tf                # Service accounts + WIF
    storage/main.tf            # google_storage_bucket
  envs/
    dev/main.tf + terraform.tfvars
    staging/main.tf + terraform.tfvars
    prod/main.tf + terraform.tfvars
  backend.tf                   # GCS remote state
```

### 4.2 Composer 3 Module

Key resource: `google_composer_environment` with Composer 3 config (no `node_config`, use `workloads_config`).

Output the `composer_dags_path` so it can be populated into `framework.yaml`.

---

### Phase 4 Definition of Done

- [ ] `terraform/modules/` contains composer, artifact_registry, iam, storage modules
- [ ] `terraform/envs/{dev,staging,prod}/` contain per-env configs
- [ ] `terraform validate` passes for all envs
- [ ] (If GCP access available) `terraform plan -var-file=terraform.tfvars` shows expected resources

**GCP verification**:
```bash
cd terraform/envs/dev
terraform init && terraform plan -var-file=terraform.tfvars
# Review plan — should show Composer 3, AR repo, GCS bucket, service account
```

---

## Phase 5: Testing

**Goal**: Comprehensive test coverage. After this phase, all components, CLI commands, and integration scenarios are tested.

---

### 5.1 Component Unit Tests

**Create**: `tests/unit/test_components.py`

Test each component's:
- Parameter validation
- `local_run()` logic with seed data and DuckDB
- `as_kfp_component()` returns a valid callable

Components to test: `BigQueryExtract`, `GCSExtract`, `BQTransform`, `WriteFeatures`, `ReadFeatures`, `TrainModel`, `EvaluateModel`, `DeployModel`.

### 5.2 CLI Tests

**Create**: `tests/unit/test_cli.py`

Test each command with mocked filesystem and GCP:
- `gml init project` creates expected scaffolding
- `gml init pipeline` creates expected files
- `gml run --local` executes pipeline
- `gml compile` generates valid files
- `gml deploy --dry-run` shows correct output
- `gml context show` displays correct values
- `gml teardown` calls correct GCP APIs (mocked)

### 5.3 Integration Tests

**Create**: `tests/integration/test_e2e.py`

Full compile + local run for all 3 use cases:
```python
def test_churn_prediction_e2e():
    """Compile + local run for churn_prediction."""

def test_sales_analytics_e2e():
    """Compile + local run for sales_analytics."""

def test_recommendation_engine_e2e():
    """Compile + local run for recommendation_engine."""

def test_generated_dags_parse_cleanly():
    """All generated DAG files can be imported without error."""

def test_generated_dags_no_framework_imports():
    """No generated DAG file imports from gcp_ml_framework."""
```

---

### Phase 5 Definition of Done

- [ ] `tests/unit/test_components.py` — all 8 components tested
- [ ] `tests/unit/test_cli.py` — all CLI commands tested
- [ ] `tests/integration/test_e2e.py` — all 3 use cases E2E
- [ ] Total test count > 220 (up from 167)
- [ ] `uv run pytest tests/ -v` — all pass
- [ ] `uv run pytest tests/ --cov=gcp_ml_framework --cov-report=term-missing` — coverage > 70%

---

## Phase 6: CI/CD

**Goal**: GitHub Actions workflows for automated testing and deployment. After this phase, PRs are auto-validated, merges auto-deploy to staging, and tags auto-deploy to prod.

---

### 6.1 Create CI Workflow

**Create**: `.github/workflows/ci.yaml`

Trigger: `pull_request` (opened, synchronize, reopened)

Steps:
1. Checkout
2. Set up Python 3.11 + uv
3. `uv sync`
4. `uv run ruff check . && uv run ruff format --check .`
5. `uv run mypy --strict gcp_ml_framework/`
6. `uv run pytest tests/unit/ -v`
7. `uv run gml compile --all`
8. For each pipeline with `trainer/`: `docker build` (no push)

### 6.2 Create CD Staging Workflow

**Create**: `.github/workflows/cd-staging.yaml`

Trigger: `push` to `main`

Steps:
1. Checkout
2. Authenticate to GCP (Workload Identity Federation)
3. Set up Python 3.11 + uv
4. Docker: auto-generate Dockerfiles, build, push with SHA tag
5. `GML_ENV_OVERRIDE=STAGING uv run gml compile --all`
6. `GML_ENV_OVERRIDE=STAGING uv run gml deploy --all`

### 6.3 Create CD Prod Workflow

**Create**: `.github/workflows/cd-prod.yaml`

Trigger: `push` tag matching `v*`

Steps:
1. Checkout at tag
2. Authenticate to GCP (WIF, prod project)
3. Docker: retag staging images with semver (don't rebuild)
4. `GML_ENV_OVERRIDE=PROD uv run gml compile --all`
5. Manual approval gate (GitHub environment: "production")
6. `GML_ENV_OVERRIDE=PROD uv run gml deploy --all`

### 6.4 Create Teardown Workflow

**Create**: `.github/workflows/teardown.yaml`

Trigger: `delete` event (branch)

Steps:
1. Authenticate to GCP (WIF, dev project)
2. `GML_ENV_OVERRIDE=DEV uv run gml teardown --branch {deleted_branch} --confirm`

---

### Phase 6 Definition of Done

- [ ] `.github/workflows/ci.yaml` exists and is valid YAML
- [ ] `.github/workflows/cd-staging.yaml` exists
- [ ] `.github/workflows/cd-prod.yaml` exists with manual approval gate
- [ ] `.github/workflows/teardown.yaml` exists
- [ ] Push a test branch → CI workflow triggers and passes
- [ ] (After merge to main) CD staging deploys DAGs + pipeline YAMLs to staging Composer

**GCP verification** (after first merge to main):
```bash
# Check staging Composer UI — DAGs should appear
# Check staging GCS bucket — compiled_pipelines/ should have YAMLs
# Check staging Artifact Registry — Docker images should have SHA tags
```

---

## Quick Reference: File Changes by Phase

| Phase | New Files | Modified Files | Deleted Files |
|-------|-----------|----------------|---------------|
| 1 | `cli/cmd_compile.py`, `tests/unit/test_components.py` (started), `tests/unit/test_utils_bq.py` | `components/base.py`, `naming.py`, `dag/tasks/bq_query.py`, `dag/tasks/vertex_pipeline.py`, `dag/compiler.py`, `cli/main.py`, `cli/cmd_run.py`, `cli/cmd_deploy.py`, `config.py`, `framework.yaml`, `components/ml/evaluate.py`, `components/ml/train.py`, `utils/bq.py`, `pyproject.toml` | `cli/cmd_promote.py`, PandasTransform |
| 2 | `docker/base/*/Dockerfile`, `scripts/docker_build.sh`, `dag/runner.py`, `pipelines/sales_analytics/`, `pipelines/recommendation_engine/`, `tests/unit/test_dag_runner.py` | `cli/cmd_run.py`, `components/ml/train.py`, existing churn example | Churn's `Dockerfile` (auto-generated instead) |
| 3 | `tests/unit/test_feature_store_client.py` | `feature_store/client.py`, `components/feature_store/write_features.py`, `components/feature_store/read_features.py`, `components/ml/train.py`, `components/ml/evaluate.py` | — |
| 4 | `terraform/` (entire directory) | — | — |
| 5 | `tests/unit/test_components.py` (full), `tests/unit/test_cli.py`, `tests/integration/test_e2e.py` | — | — |
| 6 | `.github/workflows/ci.yaml`, `cd-staging.yaml`, `cd-prod.yaml`, `teardown.yaml` | — | — |
