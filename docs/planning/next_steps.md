# Next Steps — Honest Platform Assessment

> Updated: 2026-03-03 | Based on full codebase audit of every module

---

## 1. What the Platform Can Actually Do Today

### Fully Working (verified by reading code + 167 passing tests)

**Core foundation is solid.** These modules are complete, well-tested, and production-quality:

| Module | Lines | Tests | Verdict |
|---|---|---|---|
| `naming.py` | 209 | 23 | Rock solid. Single source of truth for all GCP resource names. Frozen dataclass, cached properties, comprehensive method coverage. |
| `config.py` | 205 | 13 | Complete. Pydantic v2 layered config, git state resolution, project validation. |
| `context.py` | 111 | 9 | Complete. MLContext frozen dataclass, clean factory method, proper delegation. |
| `secrets/client.py` | 170 | 7 | Complete. Both GCP and local clients, `!secret` resolution, caching. |
| `pipeline/builder.py` | 130 | 28 | Complete. Fluent DSL works as advertised. |
| `pipeline/compiler.py` | 189 | — | Complete. Generates valid KFP v2 YAML. Cross-step wiring works for the standard ML loop. |
| `pipeline/runner.py` | 192 | — | Complete. LocalRunner (DuckDB + seed data) and VertexRunner (submit + sync/async). |
| `dag/builder.py` | 152 | 23 | **NEW.** Complete. Fluent DSL with explicit `depends_on`, topological sort, cycle detection, validation. |
| `dag/compiler.py` | 220 | 15 | **NEW.** Complete. Renders self-contained Airflow DAG files. Template vars resolved at compile time, Airflow macros preserved for runtime. |
| `dag/tasks/` | 245 | 29 | **NEW.** BQQueryTask, EmailTask, VertexPipelineTask all complete with validation. |
| `dag/factory.py` | 150 | — | Backward-compat wrapper. `discover_and_render()` handles both dag.py and pipeline.py patterns. |
| `dag/operators.py` | 79 | — | Complete. VertexPipelineOperator with lazy Airflow import. |
| `feature_store/schema.py` | 120 | 10 | Complete. YAML → typed dataclasses. |
| `utils/sql_compat.py` | 82 | 10 | 7 BQ→DuckDB translations. Works for common patterns. |
| `utils/gcs.py` | 56 | — | Complete. Upload, delete prefix, cross-project copy. |

**Total: ~2,360 lines of framework code, 167 unit tests passing.**

### What a Data Scientist Can Do Right Now

1. **Define a pipeline** in `pipelines/{name}/pipeline.py` using PipelineBuilder
2. **Run locally** with `gml run --local` — DuckDB stubs, seed CSV/Parquet, zero GCP cost
3. **Compile to KFP YAML** with `gml run --compile-only`
4. **Submit to Vertex AI** with `gml run --vertex` (full 6-step ML loop proven)
5. **Define a DAG** in `pipelines/{name}/dag.py` using DAGBuilder (BQ queries, Vertex pipelines, email notifications)
6. **Generate Airflow DAG files** with `gml deploy dags`
7. **Scaffold a new project** with `gml init project` and a new pipeline with `gml init pipeline`
8. **Inspect context** with `gml context show` (namespace, resources, GCP project)

### Two Working Example Pipelines

- **`pipelines/example_churn/`** — Full ML loop: ingest → transform → write features → train → evaluate → deploy. Includes trainer Docker container, seed data, and sklearn model.
- **`pipelines/daily_sales_etl/`** — Pure ETL DAG: BQ extract → BQ transform → email notification. Uses DAGBuilder DSL.

---

## 2. What Doesn't Work or Is Incomplete

### Broken / Non-Functional

| Item | File | Problem |
|---|---|---|
| **Feature Store client: `ensure_feature_view()`** | `feature_store/client.py:120-129` | Returns early with a try-except that does nothing. Variable `_view_id` created but unused (noqa: F841). Feature views are never actually created. |
| **Feature Store client: `trigger_sync()`** | `feature_store/client.py:165` | Computes view ID, prints a message, does nothing. No API call. |
| **WriteFeatures component: SDK workaround** | `components/feature_store/write_features.py:67-102` | Uses custom gRPC + manual LRO polling to work around a known Vertex AI SDK bug. Non-standard, fragile, takes ~10 minutes for 10 rows. |
| **DeployModel: traffic split** | `components/ml/deploy.py:91` | Always maps to deployed_model_id `"0"`. Canary deployment feature doesn't actually work. |
| **EvaluateModel: local metrics** | `components/ml/evaluate.py` | Local run returns `random.uniform(0.75, 0.95)` — completely synthetic. Data scientists see fake AUC locally, real AUC on Vertex. Misleading. |
| **`gml lint`** | Does not exist | Referenced in CLAUDE.md and README but no `cmd_lint.py` file. Not registered in `main.py`. |
| **`framework.yaml`: composer_env** | `framework.yaml` | Empty. DAG deployment to Composer will fail without this. |

### Partially Implemented

| Item | What's There | What's Missing |
|---|---|---|
| **`gml deploy features`** | CLI command exists, loads YAML schemas, calls `ensure_entity()` | Feature view creation is broken (see above). Sync trigger is a stub. |
| **`gml promote`** | CLI command exists, copies GCS prefix, generates PROD DAGs | No Model Registry promotion. No canary traffic split. No promotion metadata recorded. |
| **`gml teardown`** | CLI command exists with safety checks (DEV-only), confirmation prompt | Only deletes GCS prefix and BQ dataset. Does NOT delete: Vertex experiments, endpoints, models, Feature Store views, Composer DAGs. |
| **`GCSExtract` component** | KFP implementation exists (GCS copy with pattern matching) | `local_run()` creates empty directory — doesn't test any logic. |
| **`ReadFeatures` component** | KFP implementation reads from BQ | `local_run()` returns empty DataFrame with placeholder columns. |
| **`utils/bq.py`** | `delete_bq_dataset()` and `table_exists()` | `table_exists()` catches all exceptions and returns False — masks permission errors. |
| **`utils/logging.py`** | Hand-crafted JSON formatter | Not integrated with GCP Cloud Logging. No request IDs, traces, or severity mapping. |

### Completely Missing

| Item | Impact |
|---|---|
| **Integration tests** | `tests/integration/` exists but is empty. Zero integration coverage. |
| **Component unit tests** | No dedicated tests for BigQueryExtract, BQTransform, WriteFeatures, TrainModel, EvaluateModel, DeployModel. Only tested indirectly through pipeline builder tests. |
| **CLI tests** | No tests for any `gml` command (init, run, deploy, promote, teardown, context). |
| **CI/CD workflows** | `.github/workflows/` referenced everywhere but no actual workflow files in repo. |
| **`gml status`** | No way to check pipeline run status from CLI. |
| **`gml logs`** | No way to stream step logs from CLI. |
| **Model versioning** | Every training run writes to `latest/model.pkl`, overwriting the previous model. |
| **Experiment tracking** | `aiplatform.init(experiment=...)` is called but `log_metrics()` is never called. Metrics computed in evaluate step are thrown away. |
| **Monitoring / alerting** | No pipeline failure notifications, SLA checks, or drift detection. |
| **Batch prediction** | Only online endpoints. No nightly scoring jobs. |
| **Dataproc / Spark support** | Only BQ SQL transforms. |

---

## 3. What Is Over-Engineered

### Remove or Simplify

| Item | Why It's Over-Engineered | Action |
|---|---|---|
| **`as_airflow_operator()` on BaseComponent** | Dead code. The DAG factory uses `VertexPipelineOperator` to submit the entire pipeline as one Airflow task. Individual components never need Airflow operators. Every component inherits a default implementation that wraps `local_run()` in a `PythonOperator` — nobody calls it. | **Remove from ABC.** Delete the method and the default implementation. Reduces confusion about which layer orchestrates. |
| **`PandasTransform` component** | Has `as_kfp_component()` that raises `NotImplementedError("local-only stub")`. Local-only components that can't run on Vertex violate the framework's core promise. If someone puts this in a pipeline and runs `--vertex`, it fails. | **Either make it work on Vertex (containerized pandas) or delete it.** Currently it's a trap. |
| **Canary traffic split in DeployModel** | `traffic_split` parameter exists and is configurable, but the implementation always maps to `deployed_model_id: "0"`. Real canary requires tracking existing deployed model IDs. This belongs in `gml promote`, not in the pipeline deploy step. | **Remove traffic_split from DeployModel. Default to 100% new model.** Move canary logic to `gml promote`. |
| **`{artifact_registry}` placeholder resolution** in compiler | The compiler resolves `{artifact_registry}` in string values (compiler.py:186). Now that the serving container is a static pre-built URI, this is only used for `trainer_image`. | **Make `trainer_image` a config-level setting in `framework.yaml`** instead of a per-pipeline template string. |
| **`composer_environment_name()` in naming.py** | Returns `{namespace}-composer`, implying one Composer environment per branch. At ~$300-500/month per environment, this would bankrupt any team. Real architecture is one shared Composer per GCP project. | **Remove this method or rename to `composer_dag_prefix()`.** Composer env name comes from `framework.yaml`, not from naming convention. |
| **`gcs_dag_sync_path()` constructing a bucket name** | Constructs the Composer bucket name as `gs://{namespace}-composer-bucket/dags/`. Real Composer buckets are auto-generated with random suffixes. Must be discovered from the Composer API. | **Discover from Composer API or require explicit config in `framework.yaml`.** |
| **WriteFeatures SDK workaround** | 40 lines of custom gRPC + manual LRO polling. The Vertex AI SDK bug this works around may or may not still exist. Even when it works, it takes ~10 minutes for 10 rows because it provisions Bigtable infrastructure on every call. | **Replace with Feature Store 2.0 (BigQuery-backed)** where ingestion is a BQ write (already done) + scheduled sync. Zero blocking LRO. |

---

## 4. Highest Priority for Data Scientists

Ranked by "what blocks a data scientist from shipping an ML pipeline to production."

### Priority 1: Fix the Broken Things

These are bugs, not features. They should be fixed before adding anything new.

**1a. Fix `gml teardown` to actually clean up all resources.**
Currently only deletes GCS prefix and BQ dataset. After a data scientist merges their feature branch, these resources leak:
- Vertex AI experiments, endpoints, and models
- Feature Store entity types and views
- Composer DAGs

This costs real money. Every feature branch that merges without full cleanup accumulates GCP charges.

**1b. Fix `EvaluateModel.local_run()` to use real metrics.**
Local run returns `random.uniform(0.75, 0.95)`. A data scientist iterating locally sees `auc=0.92` and thinks their model is great. Then they submit to Vertex and get `auc=0.65`. This erodes trust in `--local` mode. Fix: load the placeholder model from train's local output and compute real metrics against seed data.

**1c. Fix `framework.yaml` defaults.**
`composer_env` is empty. A data scientist running `gml deploy dags` hits an error because there's no Composer environment configured. Either make this a required field with a validation error, or make `gml deploy dags` work without Composer (local-only mode that just generates DAG files).

### Priority 2: Close the Production Gap

These are the minimum requirements to get a pipeline running on a schedule in production.

**2a. CI/CD workflow files.**
There are zero workflow files in `.github/workflows/`. Without CI/CD:
- No automated testing on PR
- No automated deployment to STAGING on merge
- No automated promotion to PROD on tag
- Manual deployment means human error

This is the single biggest gap between "works on my laptop" and "runs in production."

**2b. Model versioning.**
Every `gml run --vertex` overwrites `latest/model.pkl`. If a training run produces a bad model, the previous good model is gone. Data scientists need:
- Versioned model paths: `gs://bucket/models/{pipeline}/{timestamp}/model.pkl`
- Model Registry parent references for lineage
- A way to roll back to the previous model version

**2c. Experiment tracking.**
The evaluate step computes `{"auc": 0.83, "f1": 0.79}` and returns it as a string. It's not logged to Vertex AI Experiments. Data scientists can't compare runs in the Vertex AI console. Add `aiplatform.log_metrics()` in the evaluate component.

### Priority 3: Developer Experience

These make data scientists more productive day-to-day.

**3a. `gml status` and `gml logs`.**
After `gml run --vertex`, the only feedback is `current state: 3` every 60 seconds. Data scientists have to navigate the GCP console to see step-level status or read logs. Two new commands:
- `gml status [pipeline]` — show pipeline run status and step progress
- `gml logs [pipeline] [step]` — stream step logs

**3b. Row-count validation in extract/transform.**
If `run_date` doesn't match seed data, BQ queries return 0 rows. The pipeline continues silently. The trainer starts provisioning a VM ($$$), then crashes 10 minutes later because the input is empty. Add early row-count validation in `BigQueryExtract` and `BQTransform`: if output is 0 rows, fail immediately with a clear error.

**3c. `--from-step` flag for partial re-runs.**
If deploy fails, the entire 20-minute pipeline re-runs. Data scientists need `gml run churn_prediction --vertex --from-step deploy` to skip completed steps. KFP caching partially addresses this but is confusing when the container image changes.

### Priority 4: Test Coverage

The framework has 167 unit tests, but they only cover ~30% of source files.

**Missing tests (in priority order):**
1. Component unit tests — BigQueryExtract, BQTransform, WriteFeatures, TrainModel, EvaluateModel, DeployModel have zero dedicated tests
2. CLI command tests — no tests for `gml init`, `gml run`, `gml deploy`, `gml promote`, `gml teardown`
3. Integration tests — the directory exists but is empty. Need: full pipeline compilation, DAG compilation, local runner with seed data
4. Feature Store client tests — `ensure_entity()`, `ensure_feature_view()` (once fixed), `get_online_features()`

---

## 5. Recommended Execution Order

| Phase | What | Why First |
|---|---|---|
| **Week 1** | Fix teardown (all resources), fix local evaluate metrics, add row-count validation | Stop money leaks, stop trust erosion |
| **Week 2** | CI/CD workflows (ci-dev, ci-stage, promote, teardown) | Unblock automated deployment |
| **Week 3** | Model versioning + experiment tracking | Unblock production model management |
| **Week 4** | Remove over-engineering (as_airflow_operator, PandasTransform, canary in deploy, composer naming) | Reduce confusion for new contributors |
| **Week 5** | Component unit tests + CLI tests | Catch regressions before they hit production |
| **Week 6** | `gml status` + `gml logs` + `--from-step` | Daily quality of life for data scientists |
| **Deferred** | Feature Store 2.0 migration, Spark/Dataproc, batch prediction, monitoring | Not blocking anyone today |

---

## 6. Module Health Summary

| Module | Lines | Tests | Health | Notes |
|---|---|---|---|---|
| naming.py | 209 | 23 | **Green** | No issues |
| config.py | 205 | 13 | **Green** | No issues |
| context.py | 111 | 9 | **Green** | No issues |
| secrets/client.py | 170 | 7 | **Green** | No issues |
| pipeline/builder.py | 130 | 28 | **Green** | Sequential only (by design) |
| pipeline/compiler.py | 189 | 0 | **Yellow** | Works but cross-step wiring is heuristic-based (`hasattr` duck typing). Fragile with custom components. |
| pipeline/runner.py | 192 | 0 | **Yellow** | Works but hard-coded param keys (`input_path`, `db_conn`). No error handling in VertexRunner. |
| dag/builder.py | 152 | 23 | **Green** | New. Clean DSL with validation. |
| dag/compiler.py | 220 | 15 | **Green** | New. Generates valid Airflow code. |
| dag/tasks/ | 245 | 29 | **Green** | New. 3 task types complete. |
| dag/factory.py | 150 | 0 | **Yellow** | Backward-compat wrapper. Works but no dedicated tests. |
| dag/operators.py | 79 | 0 | **Yellow** | Works but no dedicated tests. |
| components/base.py | 85 | 0 | **Yellow** | `as_airflow_operator()` is dead code. |
| components/ingestion/ | 171 | 0 | **Yellow** | No dedicated tests. GCSExtract local_run is empty stub. |
| components/transformation/ | 142 | 0 | **Yellow** | No dedicated tests. PandasTransform can't run on Vertex. |
| components/feature_store/ | 189 | 0 | **Red** | WriteFeatures uses fragile SDK workaround. ReadFeatures local_run returns empty DF. |
| components/ml/train.py | 111 | 0 | **Yellow** | No dedicated tests. Local run writes placeholder JSON. |
| components/ml/evaluate.py | 130 | 0 | **Red** | Local run returns random metrics. Hard-coded binary classification. |
| components/ml/deploy.py | 106 | 0 | **Red** | Traffic split doesn't work. No dedicated tests. |
| feature_store/schema.py | 120 | 10 | **Green** | No issues |
| feature_store/client.py | 165 | 0 | **Red** | `ensure_feature_view()` is non-functional. `trigger_sync()` is a stub. |
| cli/ (all commands) | ~600 | 0 | **Yellow** | All commands implemented, none tested. |
| utils/sql_compat.py | 82 | 10 | **Green** | Limited scope (7 translations) but works |
| utils/gcs.py | 56 | 0 | **Yellow** | Complete but untested |
| utils/bq.py | 26 | 0 | **Red** | `table_exists()` swallows all exceptions |
| utils/logging.py | 19 | 0 | **Red** | Not production-ready. No GCP integration. |
