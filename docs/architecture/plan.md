# Architecture Plan

## Vision

Data scientists define ML pipelines and data workflows as Python code, run them locally with zero GCP cost, and promote to Google Cloud Platform with one command. Every GCP resource name encodes its origin: `{team}-{project}-{branch}`.

## Core Principles

| Principle | Meaning |
|---|---|
| Branch-based isolation | Each git branch gets its own GCS prefix, BQ dataset, Vertex experiment, Feature Store views, Composer DAG IDs |
| Environment agnostic | No `if env == "prod"`. Git state determines environment. Config is injected. |
| Two-level orchestration | Composer schedules and coordinates. Vertex AI executes ML steps. |
| Feature Store foundation | All features organized around business entities (User, Item, Session) using v2 BQ-native APIs |
| Convention over config | Follow conventions = zero boilerplate. Overrides are opt-in. |
| Self-contained DAGs | Generated Airflow DAG files have zero framework imports. Config is inlined at compile time. |

## Naming Convention

### Namespace: `{team}-{project}-{branch}`

| Resource | Pattern | Example |
|---|---|---|
| GCS bucket | `{team}-{project}` | `dsci-churn-pred` |
| GCS prefix | `gs://{bucket}/{branch}/` | `gs://dsci-churn-pred/feature-xyz/` |
| BQ dataset | `{team}_{project}_{branch_safe}` (max 30 chars) | `dsci_churn_pred_feature_xyz` |
| Vertex Experiment | `{namespace}-{pipeline}-exp` | `dsci-churn-pred-main-churn-exp` |
| Composer DAG ID | `{bq_dataset}__{pipeline}` | `dsci_churn_pred_main__churn` |
| Feature View | `{entity}_{group}_{branch_safe}` | `user_behavioral_main` |
| Docker tag | `{branch_safe}-{sha}` | `main-a1b2c3d` |
| Secret name | `{namespace}-{key}` | `dsci-churn-pred-main-db-password` |

### Branch to Environment Mapping

| Git State | Environment | GCP Project |
|---|---|---|
| `feature/*`, `hotfix/*`, other | DEV | `{project}-dev` |
| `main` | STAGING | `{project}-staging` |
| Release tag `v*` | PROD | `{project}-prod` |
| `prod/*` | PROD (Experiment) | `{project}-prod` |

## System Layers

```
+--------------------------------------------------------------+
|  DATA SCIENTIST INTERFACE                                     |
|  pipelines/{name}/pipeline.py    pipelines/{name}/dag.py      |
|  framework.yaml                  feature_schemas/*.yaml        |
|  gml CLI                                                      |
+--------------------------------------------------------------+
|  FRAMEWORK CORE                                               |
|  naming.py -> config.py -> context.py -> secrets/             |
+--------------------------------------------------------------+
|  PIPELINE ENGINE                  DAG ENGINE                  |
|  builder.py -> compiler.py       builder.py -> compiler.py   |
|  runner.py (local + vertex)      runner.py (DuckDB local)    |
+--------------------------------------------------------------+
|  COMPONENT LIBRARY                TASK LIBRARY                |
|  ingestion/ -> transformation/    BQQueryTask                 |
|  feature_store/ -> ml/            VertexPipelineTask          |
|  (8 components)                   EmailTask                   |
+--------------------------------------------------------------+
|  GCP SERVICES                                                 |
|  Vertex AI | BigQuery | GCS | Feature Store v2 | Composer 3  |
+--------------------------------------------------------------+
|  INFRASTRUCTURE (Terraform)                                   |
|  Composer 3 | Artifact Registry | IAM + WIF | GCS buckets    |
+--------------------------------------------------------------+
```

## Two DSLs

### PipelineBuilder (Vertex AI)

For ML workflows. Steps run sequentially on Vertex AI Pipelines. Each step is a KFP v2 component with automatic cross-step data wiring.

```
pipeline.py -> PipelineBuilder -> PipelineDefinition
    -> PipelineCompiler -> KFP v2 YAML -> Vertex AI Pipelines
    -> LocalRunner -> DuckDB + pandas stubs (no GCP)
```

Components: `BigQueryExtract`, `GCSExtract`, `BQTransform`, `WriteFeatures`, `ReadFeatures`, `TrainModel`, `EvaluateModel`, `DeployModel`.

### DAGBuilder (Cloud Composer)

For orchestration workflows with parallel tasks, fan-out/fan-in, notifications, and multi-pipeline coordination. Supports explicit `depends_on` for arbitrary DAG shapes.

```
dag.py -> DAGBuilder -> DAGDefinition
    -> DAGCompiler -> standalone Airflow DAG Python file -> Composer GCS bucket
    -> DAGLocalRunner -> DuckDB + console stubs (no GCP)
```

Tasks: `BQQueryTask`, `VertexPipelineTask`, `EmailTask`.

Generated DAG files are self-contained Python — no `gcp_ml_framework` imports at Airflow parse time.

## Config System

Resolution order (later wins):

```
framework defaults -> framework.yaml -> pipeline/config.yaml -> env vars -> CLI flags
```

All config via Pydantic v2 `BaseSettings`. Environment variables use `GML_` prefix, nested via `__` delimiter (e.g., `GML_GCP__REGION=europe-west1`).

## Infrastructure Responsibilities

| Terraform (long-lived, shared) | Framework (ephemeral, per-branch) |
|-------------------------------|----------------------------------|
| Cloud Composer 3 environments | BQ datasets |
| Artifact Registry repos | GCS prefixes within buckets |
| GCS buckets | Vertex AI experiments, endpoints, models |
| IAM roles + service accounts | Composer DAG files |
| Workload Identity Federation | Feature Store resources |

Terraform modules: `terraform/modules/{composer,artifact_registry,iam,storage}`.
Per-env configs: `terraform/envs/{dev,staging,prod}/`.

## CI/CD Flow

```
feature/* push  -> ci-dev:     lint, test, compile, deploy DAGs/features to DEV
main merge      -> ci-stage:   full tests, deploy to STAGE, run pipelines on Vertex
release tag v*  -> promote:    copy STAGE -> PROD artifacts, sync PROD DAGs
PR close        -> teardown:   delete ephemeral DEV resources
```

PROD is never deployed to from source. Only validated STAGING artifacts are promoted.

## Feature Store v2 Integration

Uses Vertex AI Feature Store v2 (BQ-native):

- **FeatureGroup** — registers a BQ table as a feature source (metadata only, no data movement)
- **FeatureView** — connects a FeatureGroup to a FeatureOnlineStore with sync
- **FeatureOnlineStore** — Bigtable-backed online serving (sub-10ms p99)

Feature views are branch-namespaced to prevent DEV contamination of PROD.

## Model Management

- **Versioned paths:** Model artifacts stored at `{gcs_prefix}/models/{pipeline}/{run_id}/model.pkl`
- **Experiment tracking:** Metrics logged to Vertex AI Experiments via `aiplatform.log_metrics()`
- **Quality gates:** `EvaluateModel` halts the pipeline if any metric falls below its threshold
- **Canary deployments:** `DeployModel` supports traffic splitting (e.g., 10% new / 90% current)

## Key Design Decisions

| Decision | Rationale |
|---|---|
| KFP v2 + Airflow | KFP for ML (artifacts, lineage, GPUs). Airflow for scheduling and cross-pipeline deps. |
| Branch = namespace | Isolation is structural. No human discipline required. |
| Pydantic v2 config | Validation at load time, IDE autocomplete, clear errors. |
| DuckDB for local | SQL-compatible with BigQuery, zero infrastructure, in-process. |
| Feature Store v2 (BQ-native) | No data movement for offline features. Bigtable for online serving. |
| Feature schemas in YAML | Non-engineers can read/edit. Diff-friendly. |
| `gml` CLI (Typer) | Type-safe, self-documenting, testable with CliRunner. |
| Compiled DAGs (no imports) | Airflow parses DAGs every 30s. Zero import overhead. |
| N2/C3 machine types | Modern Compute Engine families. No legacy N1. |
| Composer 3 | workloads_config for fine-grained resource control. No node_config. |
| Terraform for infra | Reproducible, auditable, multi-env. |
| Single region: us-central1 | Simplifies initial deployment. Multi-region deferred. |
