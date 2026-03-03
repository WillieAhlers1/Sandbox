# Next Steps

> Updated: 2026-03-03

## P0 — Composer Orchestration (Critical Path)

### 1. DAG Factory Rewrite

The current `dag/factory.py` wraps a single Vertex pipeline in an Airflow DAG. It needs to support arbitrary task composition — BQ queries, notifications, sensors, Vertex pipelines, and parallel/conditional logic.

**New approach:** `DAGBuilder` DSL (see [feature_plan.md](feature_plan.md)) that mirrors `PipelineBuilder` but targets Composer DAGs.

**Status:** Design complete. Implementation in progress on `feature_dagFactory` branch. New files:
- `gcp_ml_framework/dag/builder.py` — DAGBuilder fluent DSL
- `gcp_ml_framework/dag/compiler.py` — DAG definition → Airflow DAG file
- `gcp_ml_framework/dag/tasks/` — task components (BQ, Vertex, notification, sensor, etc.)

### 2. `gml deploy dags`

- Generate DAG files via DAG factory
- Sync to Composer GCS bucket (discover bucket from Composer API, not construct it)
- Validate DAG syntax before upload

### 3. CI/CD Workflows

| Workflow | Trigger | Action |
|---|---|---|
| `ci-dev.yaml` | Push to `feature/*` | Lint, test, compile-only |
| `ci-stage.yaml` | Merge to `main` | Full test suite, deploy to STAGE, run pipelines |
| `promote.yaml` | Release tag `v*` | Copy STAGE artifacts → PROD |
| `teardown.yaml` | Branch delete / PR close | Delete ephemeral DEV resources |

## P1 — Production Readiness

### 4. `gml promote` (STAGE → PROD)

Copy compiled YAML + model from STAGE to PROD. No recompilation. Record promotion metadata.

### 5. `gml teardown`

Delete branch-specific DEV resources: BQ dataset, GCS prefix, Vertex experiments, Feature Store views, Composer DAGs.

### 6. Model Versioning

Currently writes to `latest/model.pkl`. Need versioned paths (`{timestamp}/model.pkl`) and Model Registry parent references.

### 7. Experiment Tracking

Experiment is auto-created but no metrics are logged. Wire `aiplatform.log_metrics()` in evaluate step.

## P2 — Team Adoption

### 8. Feature Store

Migrate from legacy API to Feature Store 2.0 (BigQuery-backed). Or decouple feature writes from the ML pipeline entirely.

### 9. `gml lint`

Naming convention enforcement — catch hardcoded project IDs or bucket names in pipeline code.

### 10. Integration Tests

- Compile pipeline and verify YAML structure
- Submit to Vertex AI in test project
- Validate DAG factory output is valid Airflow syntax

### 11. Monitoring & Alerting

Pipeline failure notifications, SLA checks, model drift detection.

## Simplification Opportunities

- **Remove `as_airflow_operator()` from BaseComponent** — dead code, DAG factory uses `VertexPipelineOperator` instead
- **Make `trainer_image` a config-level setting** — `{artifact_registry}` placeholder only used for trainer image
- **Decouple Feature Store writes** from the train → evaluate → deploy loop
- **Default deploy to 100% traffic** — canary logic belongs in `gml promote`, not the pipeline
