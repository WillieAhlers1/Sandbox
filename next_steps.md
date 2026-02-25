# Next Steps — GCP ML Framework

## Current State (2026-02-25)

The core ML loop works end-to-end on Vertex AI:

```
bigquery-extract → bq-transform → write-features → train-model → evaluate-model → deploy-model
```

All 6 steps succeed on Vertex AI. The platform compiles Python DSL to KFP v2 YAML,
runs locally with DuckDB stubs, and submits to Vertex AI Pipelines.

**What works:**
- Pipeline DSL (`PipelineBuilder`) — clean API, data scientists only edit `pipeline.py`
- Component library — BaseComponent ABC with 7 built-in components
- KFP v2 compilation with cross-step data flow wiring
- Local runner with DuckDB, seed data, SQL compatibility layer
- Vertex AI runner with sync/async, caching control, `--run-date` override
- Naming convention — `{team}-{project}-{branch}`, BQ-safe variants
- Config system (Pydantic v2) — layered: framework.yaml → pipeline config → env → CLI
- MLContext — single runtime context object, no globals
- Secrets — `!secret` refs, GCP Secret Manager, local env fallback
- Feature Store — schema YAML parser, write via legacy API (slow)
- 99 unit tests passing, ruff clean

---

## P0 — Platform Objective: Composer Orchestration

The stated goal is: **Composer DAGs orchestrate Vertex AI Pipelines for ML workflows.**
This is the critical path. Nothing below matters until this works.

### 1. DAG Factory

**Status:** Not started. `gcp_ml_framework/dag/` directory is referenced but empty.

**What it needs to do:**
- Read `PipelineDefinition.schedule` (e.g. `"0 6 * * 1"`)
- Generate a Composer DAG Python file that:
  - Compiles the pipeline to KFP YAML (or uses a pre-compiled artifact)
  - Calls `VertexRunner.submit()` to trigger the Vertex AI Pipeline
  - Monitors the pipeline run to completion
  - Handles retries and alerting on failure
- Output file: `dags/{namespace}--{pipeline_name}.py`

**Design decision:** The DAG should be a thin orchestrator — one Airflow task that
submits and monitors the Vertex Pipeline. Individual pipeline steps should NOT be
Airflow tasks. Vertex AI handles step-level orchestration, retries, and caching.

This means `as_airflow_operator()` on BaseComponent is unnecessary for this architecture.
Consider removing it from the ABC to reduce confusion.

### 2. `gml deploy dags`

**Status:** Not started.

**What it needs to do:**
- Run the DAG factory to generate DAG files
- Sync generated DAGs to the Composer GCS bucket (`gs://{namespace}-composer/dags/`)
- Validate DAG syntax before uploading (Airflow import check)

### 3. CI/CD Workflows

**Status:** Not started. `.github/workflows/` is referenced but empty.

**Needed workflows:**
- `ci-dev.yaml` — On PR: lint, test, compile-only. Fast feedback.
- `ci-stage.yaml` — On merge to main: compile, submit to STAGE Vertex, run integration tests.
- `promote.yaml` — On release tag: copy validated STAGE artifacts to PROD (never recompile).
- `teardown.yaml` — On branch delete: clean up ephemeral DEV resources.

---

## P1 — Production Readiness

### 4. `gml promote`

**Status:** Not started.

The STAGE → PROD promotion flow. Must:
- Copy compiled YAML from STAGE GCS to PROD GCS (never recompile)
- Upload model from STAGE to PROD Model Registry
- Deploy to PROD endpoint with canary traffic split
- Record promotion metadata (who, when, from which STAGE run)

This is the "no deploy from source to prod" guarantee. Only validated STAGE
artifacts are promoted.

### 5. `gml teardown`

**Status:** Not started.

Ephemeral DEV resource cleanup for feature branches. Must delete:
- BQ dataset (`{team}_{project}_{branch_safe}`)
- GCS prefix (`gs://{team}-{project}/{branch}/`)
- Vertex AI Endpoints and Models for the namespace
- Feature Store entities for the branch
- Composer DAGs for the namespace

Critical for cost control. Every feature branch leaks GCP resources without this.

### 6. Model Versioning

**Status:** Not implemented. Currently writes to `latest` always.

The GCS model path is `gs://bucket/models/{pipeline_name}/latest/model.pkl`.
Every training run overwrites the previous model. Need:
- Versioned paths: `gs://bucket/models/{pipeline_name}/{timestamp}/model.pkl`
- Model Registry versioning via `Model.upload()` with parent model reference
- `latest` symlink or pointer for convenience

### 7. Experiment Tracking

**Status:** Partially implemented. Experiment is auto-created but no metrics logged.

`aiplatform.init(experiment=experiment_name)` creates the experiment, but neither
the train nor evaluate step logs metrics to it. The evaluate step computes
`{"auc": 0.83, "f1": 0.79}` — these should be logged via
`aiplatform.log_metrics()` so data scientists can compare runs in the Vertex AI
Experiments UI.

---

## P2 — Team Adoption

### 8. Feature Store Improvements

**Write-features is slow (~10 min for 10 rows).** The legacy Feature Store API
(`Featurestore` → `EntityType` → `ingest_from_bq`) provisions Bigtable
infrastructure on every call. Options:

1. **Migrate to Feature Store 2.0** (`FeatureOnlineStore` + `FeatureView`) —
   uses BQ as offline store, syncs to Bigtable on schedule. Ingestion becomes a
   BQ write (already done in bq-transform) + scheduled sync. No blocking LRO.

2. **Decouple from the pipeline** — Feature writes don't need to block training.
   Run as a separate Composer task after the pipeline succeeds.

3. **Use BigQuery Feature Store** — Newer approach, features served from BQ
   directly. Zero ingestion overhead.

**`gml deploy features`** is also not started. Should provision Feature Store
resources from `feature_schemas/*.yaml`.

### 9. `gml lint`

**Status:** Not started.

Naming convention enforcement. Should verify all GCP resource names follow
`{team}-{project}-{branch}` pattern. Useful in CI to catch hardcoded project IDs
or bucket names in pipeline code.

### 10. Integration Tests

**Status:** `tests/integration/` exists but is empty.

Need tests that:
- Compile a pipeline and verify the YAML structure
- Submit to Vertex AI in a test project and verify step completion
- Test the DAG factory output is valid Airflow syntax

### 11. Monitoring and Alerting

**Status:** Not started.

- Pipeline failure notifications (Slack, email, PagerDuty)
- SLA checks in Composer DAGs (alert if pipeline takes >X minutes)
- Model quality drift detection (compare current metrics to historical baseline)

---

## Over-Engineering to Simplify

### `as_airflow_operator()` on BaseComponent

If the architecture is "Composer submits a single Vertex Pipeline," then individual
components don't need Airflow operator implementations. The DAG has one task:
submit and monitor. Remove from the ABC to reduce confusion and the implementation
burden on custom components.

### `{artifact_registry}` placeholder resolution

The compiler resolves `{artifact_registry}` in string values at compile time. Now
that the serving container is a static pre-built URI, this is only used for the
trainer image. Consider making `trainer_image` a config-level setting in
`framework.yaml` rather than a per-pipeline template string.

### Feature Store in the ML pipeline

Feature Store writes shouldn't block the train → evaluate → deploy loop. Decouple
into a separate concern (scheduled sync or post-pipeline Composer task).

### Canary deployment in the deploy component

The `traffic_split` logic hardcodes `"0"` as the deployed_model_id key. Proper
canary deployment requires knowing existing deployed model IDs and managing traffic
redistribution. This is complex and belongs in `gml promote`, not in the pipeline.
For the pipeline deploy step, default to 100% traffic to the new model.

---

## Data Scientist Pain Points

### Silent 0-row failures
If `run_date` doesn't match seed data, BQ queries return 0 rows. Pipeline
continues, trainer crashes after 10 min of VM provisioning. Add early row-count
validation in the bigquery-extract and bq-transform components.

### Local run doesn't match Vertex
Local evaluate uses random metrics; Vertex uses real sklearn. Data scientists see
`auc=0.92` locally, then `auc=0.83` on Vertex. Consider training a real model
locally in `local_run()` too.

### No pipeline progress visibility
After `gml run --vertex`, the only feedback is `current state: 3` every 60
seconds. Add step-level status polling or log streaming to the CLI.

### No single-step re-run
If deploy fails, the entire pipeline re-runs (~20 min). Add a `--from-step` flag
or rely on KFP caching (but caching is confusing when the container image changes).

### No `gml status` or `gml logs`
Can't check pipeline status or view step logs from the CLI. Have to navigate
the GCP console manually.

### Pipeline schedule is defined but unused
`schedule="0 6 * * 1"` is stored in PipelineDefinition but nothing reads it.
No DAG generated, no Cloud Scheduler configured. Data scientists define a schedule
and nothing happens.

---

## Deploy-Model Step Latency

The deploy step takes 15-25 minutes because `endpoint.deploy()` provisions
prediction VMs:

1. **Model.upload()** — registers model to Model Registry (~1 min)
2. **Endpoint.create()** — creates the endpoint resource (~1 min, or instant if exists)
3. **endpoint.deploy()** — provisions VMs, pulls serving container, loads model,
   runs health checks (~15-20 min for first deployment)

This is inherent to Vertex AI Endpoints. Mitigation:
- Use **dedicated endpoints** that persist across pipeline runs (the component
  already does get-or-create). First deploy is slow, subsequent deploys reuse VMs.
- Use **Vertex AI Prediction with serverless endpoints** (Preview) for faster
  cold starts.
- Accept the latency as a one-time cost per model version — production models
  don't need to deploy every hour.
