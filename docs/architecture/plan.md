# Architecture Plan

## Vision

Data scientists define ML pipelines as Python code, run locally, and promote to GCP with one command. Every GCP resource name encodes its origin: `{team}-{project}-{branch}`.

## Core Principles

| Principle | Meaning |
|---|---|
| Branch-based isolation | Each git branch gets its own GCS prefix, BQ dataset, Vertex experiment, Feature Store views |
| Environment agnostic | No `if env == "prod"`. Git state determines environment. Config is injected. |
| Feature Store foundation | All features organized around business entities (User, Item, Session) |
| Convention > Config | Follow conventions = zero boilerplate. Overrides are opt-in. |

## Naming Convention

### Namespace: `{team}-{project}-{branch}`

| Resource | Pattern | Example |
|---|---|---|
| GCS path | `gs://{team}-{project}/{branch}/` | `gs://dsci-churn-pred/feature-xyz/` |
| BQ dataset | `{team}_{project}_{branch_safe}` | `dsci_churn_pred_feature_xyz` |
| Vertex Experiment | `{namespace}-{pipeline}-exp` | `dsci-churn-pred-main-churn-exp` |
| Composer DAG ID | `{namespace_bq}__{pipeline}` | `dsci_churn_pred_main__churn` |
| Feature View | `{entity}_{group}_{branch_safe}` | `user_behavioral_main` |
| Docker tag | `{branch_safe}-{sha}` | `main-a1b2c3d` |

### Branch → Environment Mapping

| Git State | Environment | GCP Project |
|---|---|---|
| `feature/*`, `hotfix/*` | DEV | `{project}-dev` |
| `main` | STAGE | `{project}-staging` |
| Release tag `v*` | PROD | `{project}-prod` |
| `prod/*` | PROD (Experiment) | `{project}-prod` |

## System Layers

```
┌─────────────────────────────────────────────────────────────┐
│  DATA SCIENTIST INTERFACE                                    │
│  pipelines/{name}/pipeline.py    feature_schemas/*.yaml      │
│  framework.yaml                  gml CLI                     │
├─────────────────────────────────────────────────────────────┤
│  FRAMEWORK CORE                                              │
│  naming.py → config.py → context.py → secrets/               │
├─────────────────────────────────────────────────────────────┤
│  PIPELINE ENGINE                                             │
│  builder.py → compiler.py → runner.py (local + vertex)       │
├─────────────────────────────────────────────────────────────┤
│  COMPONENT LIBRARY                                           │
│  ingestion/ → transformation/ → feature_store/ → ml/         │
├─────────────────────────────────────────────────────────────┤
│  ORCHESTRATION                                               │
│  dag/builder.py → dag/compiler.py → dag/tasks/               │
├─────────────────────────────────────────────────────────────┤
│  GCP SERVICES                                                │
│  Vertex AI │ BigQuery │ GCS │ Feature Store │ Composer       │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline DSL

```python
pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(query="...", output_table="raw"))
    .transform(BQTransform(sql_file="sql/features.sql", output_table="features"))
    .train(TrainModel(trainer_image="...", machine_type="n1-standard-8"))
    .evaluate(EvaluateModel(metrics=["auc"], gate={"auc": 0.78}))
    .deploy(DeployModel(endpoint_name="churn-classifier"))
    .build()
)
```

Generates both KFP v2 YAML (Vertex AI) and Composer DAGs from a single definition.

## Config System

Resolution order (later wins):

```
framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags
```

All config via Pydantic v2 `BaseSettings`. Env vars use `GML_` prefix, nested via `__` delimiter.

## CI/CD Flow

```
feature/* push  → ci-dev:     lint, test, compile-only, deploy DAGs/features to DEV
main merge      → ci-stage:   full tests, deploy to STAGE, run pipelines on Vertex
release tag v*  → promote:    copy STAGE → PROD artifacts, sync PROD DAGs
PR close        → teardown:   delete ephemeral DEV resources
```

PROD is never deployed to from source. Only validated STAGE artifacts are promoted.

## Implementation Phases

1. **Phase 1 (Wk 1-2):** Package scaffold, naming, config, context, secrets, `gml init`
2. **Phase 2 (Wk 2-3):** Component library (BaseComponent, all built-ins, unit tests)
3. **Phase 3 (Wk 3-4):** Pipeline DSL, DAG factory, runners (local/vertex/compile-only)
4. **Phase 4 (Wk 4-5):** Feature Store integration (schema parser, client, deploy)
5. **Phase 5 (Wk 5-6):** CLI commands (deploy, promote, teardown, lint)
6. **Phase 6 (Wk 6-7):** CI/CD workflows, bootstrap script, e2e example, docs

## Key Design Decisions

| Decision | Rationale |
|---|---|
| KFP v2 + Airflow | KFP for ML (artifacts, lineage, GPUs). Airflow for scheduling and cross-pipeline deps. |
| Branch = namespace | Isolation is structural. No human discipline required. |
| Pydantic config | Validation at load time, IDE autocomplete, clear errors. |
| DuckDB for local | SQL-compatible with BigQuery, zero infrastructure, in-process. |
| Feature schemas in YAML | Non-engineers can read/edit. Diff-friendly. |
| `gml` CLI over Makefiles | Type-safe, self-documenting, testable. |
| Bigtable online serving | Sub-10ms p99 for real-time inference. |
| Single region: us-central1 | Simplifies Phase 1. Multi-region deferred. |
