# Platform Project Guideline

> The definitive reference for the GCP ML/Data Orchestration Platform.
> Version: Final | Updated: 2026-03-05

---

## 1. Vision & Goals

**One sentence**: Data scientists define workflows in Python, the platform handles infrastructure, pipelining, CI/CD, containerization, versioning, and deployment across three isolated GCP environments.

### Goals

| # | Goal | Measure of Success |
|---|------|-------------------|
| G1 | Minimal friction for data scientists | Time from "code done" to "running in staging" < 1 merge |
| G2 | End-to-end orchestration | Every workload is a Composer DAG; ML tasks trigger Vertex AI Pipelines |
| G3 | Branch isolation | Feature branches get ephemeral resources; no cross-environment contamination |
| G4 | Zero manual infrastructure | CI/CD handles builds, deploys, versioning, and teardown automatically |
| G5 | Three proven use cases | Pure ML, pure ETL (non-linear), and hybrid — all working end-to-end |

### Non-Goals (Avoid Over-Engineering)

- Multi-region deployment (us-central1 only)
- A/B testing framework
- Real-time streaming pipelines
- Custom Airflow plugins or operators
- Spark/Dataproc support (BQ SQL is sufficient)
- Batch prediction (deferred)
- Model monitoring/drift detection (deferred)

---

## 2. GCP Stack

We target the latest generally available offerings. Versions in `pyproject.toml` are for the **framework's own development and CI/CD environment** — Composer has its own managed runtime (see Section 11).

| Component | Version | Notes |
|-----------|---------|-------|
| **Cloud Composer 3** | GA (March 2025) | Serverless, DCU billing, no user-managed GKE. Composer 2 EOL Sep 2026. |
| **Airflow** | 2.10.x | Stable on Composer 3. Airflow 3 preview available but not GA. |
| **google-cloud-aiplatform** | ≥1.136 | Vertex AI SDK |
| **kfp** | ≥2.15,<3 | KFP v2 SDK. Used only in CI/CD for compilation, not needed in Composer. |
| **apache-airflow-providers-google** | ≥20.0 | Pre-installed in Composer 3. Used in generated DAG files. |
| **Python** | ≥3.11 | Aligned with Composer 3 runtime |
| **Vertex AI Feature Store** | v2 (BQ-native) | v1 sunsetting May 2026 / full shutdown Feb 2027 |
| **Artifact Registry** | Current | Cleanup policies GA, vulnerability scanning available |

### Machine Types

Do **not** use N1-standard (legacy). Use current-generation families:

| Workload | Machine Type | Notes |
|----------|-------------|-------|
| CPU data processing | **n2-standard-8** or **c3-standard-8** | 20%+ better price-performance vs N1 |
| GPU training (standard) | **a2-highgpu-1g** (A100) | Deep learning, model training |
| GPU training (large-scale) | **a3-highgpu-8g** (H100) | LLMs, large models |
| Inference / light training | **g2-standard-4** (L4) | Cost-effective inference |

### Cloud Composer 3 vs Composer 2

| Aspect | Composer 2 | Composer 3 |
|--------|------------|------------|
| Architecture | User-managed GKE cluster | Serverless (GKE in Google's tenant project) |
| Billing | Pay for GKE nodes | Data Compute Units (DCUs) — blended vCPU+RAM |
| Networking | Complex VPC config required | Simplified — no cluster networking to manage |
| DAG deployment | GCS bucket sync | GCS bucket sync (same mechanism) |
| KubernetesPodOperator | Direct cluster access | Workloads scale independently; no pod affinity |

---

## 3. The Unified Mental Model: Everything Is a DAG

### 3.1 Core Principle

Every workload on this platform is orchestrated by a Composer DAG. There is no other path to production. This gives us:

- **One scheduling system** (Composer/Airflow)
- **One monitoring surface** (Composer UI + Airflow logs)
- **One deployment mechanism** (`gml deploy`)
- **One dependency model** (DAG task dependencies)

An ML pipeline (Vertex AI) is not a separate thing — it's a **task within a DAG**. The DAG triggers it, waits for it, and continues with downstream tasks.

### 3.2 Three Use Case Patterns

A data scientist has ONE decision per use case:

```
"Is my workload pure ML, pure ETL, or a mix?"

  Pure ML    → Write pipeline.py using PipelineBuilder
               Platform auto-wraps it in a single-task Composer DAG
               Data scientist never writes Airflow code

  Pure ETL   → Write dag.py using DAGBuilder
               Tasks run as native Airflow operators

  Hybrid     → Write dag.py using DAGBuilder
               Include VertexPipelineTask(s) for ML steps
               Include regular tasks for ETL/notification steps
```

No Terraform, no Docker commands, no Airflow boilerplate, no GCP console clicks.

### 3.3 What Happens Under the Hood

```
Data scientist writes:              Platform generates (gml compile):

pipeline.py (PipelineBuilder)       1. KFP v2 YAML → compiled_pipelines/{name}.yaml
    │                               2. Airflow DAG → dags/{namespace}__{name}.py
    │                               3. Auto-detects trainer/ → Docker image built by CI/CD
    ▼
dag.py (DAGBuilder)                 1. Airflow DAG → dags/{namespace}__{name}.py
    │                               2. Per VertexPipelineTask:
    │                                    KFP v2 YAML → compiled_pipelines/{vp_name}.yaml
    ▼                               3. Auto-detects trainer/ → Docker image built by CI/CD

gml compile                         Validates all artifacts generate cleanly
gml deploy                          Uploads DAGs + YAMLs to Composer 3 GCS bucket
```

---

## 4. Architecture

### 4.1 System Layers

```
┌───────────────────────────────────────────────────────────────────────────┐
│                      DATA SCIENTIST INTERFACE                             │
│                                                                           │
│  pipelines/{name}/pipeline.py    Pure ML → auto-wrapped in DAG            │
│  pipelines/{name}/dag.py         ETL or Hybrid → explicit DAG             │
│  pipelines/{name}/config.yaml    Per-use-case overrides                   │
│  pipelines/{name}/trainer/       Training code (train.py + requirements)  │
│  pipelines/{name}/sql/           SQL files (BQ queries)                   │
│  pipelines/{name}/seeds/         Local test data                          │
│  framework.yaml                  Project identity + GCP config            │
│  feature_schemas/*.yaml          Entity feature definitions               │
│  gml CLI                         All commands                             │
├───────────────────────────────────────────────────────────────────────────┤
│                      FRAMEWORK CORE                                       │
│                                                                           │
│  naming.py ──→ config.py ──→ context.py ──→ secrets/client.py             │
│  (resource       (layered       (immutable      (Secret Manager           │
│   names)          config)        runtime)        + !secret refs)          │
├───────────────────────────────────────────────────────────────────────────┤
│                      ORCHESTRATION LAYER (Composer 3 DAGs)                │
│                                                                           │
│  dag/builder.py ──→ dag/compiler.py ──→ dag/factory.py                    │
│  (DAGBuilder         (DAGDefinition       (auto-discovery:                │
│   fluent DSL)         → Airflow .py)       pipeline.py + dag.py)          │
│                                                                           │
│  dag/tasks/                                                               │
│  ├── bq_query.py         BigQueryInsertJobOperator                        │
│  ├── email.py            EmailOperator                                    │
│  └── vertex_pipeline.py  CreatePipelineJobOperator (triggers Vertex AI)   │
├───────────────────────────────────────────────────────────────────────────┤
│                      ML PIPELINE ENGINE (Vertex AI Pipelines)             │
│                                                                           │
│  pipeline/builder.py ──→ pipeline/compiler.py ──→ pipeline/runner.py      │
│  (PipelineBuilder         (PipelineDefinition      (LocalRunner +         │
│   fluent DSL)              → KFP v2 YAML)           VertexRunner)         │
│                                                                           │
│  components/                                                              │
│  ├── ingestion/       BigQueryExtract, GCSExtract                         │
│  ├── transformation/  BQTransform                                         │
│  ├── feature_store/   WriteFeatures, ReadFeatures (BQ-backed v2)          │
│  └── ml/              TrainModel, EvaluateModel, DeployModel              │
├───────────────────────────────────────────────────────────────────────────┤
│                      INFRASTRUCTURE                                       │
│                                                                           │
│  terraform/               Shared infra (Composer 3, AR, IAM, buckets)     │
│  docker/base/             Base images (base-python, base-ml)              │
│  .github/workflows/       CI/CD pipelines                                 │
│  scripts/bootstrap.sh     One-time GCP project setup                      │
├───────────────────────────────────────────────────────────────────────────┤
│                      GCP SERVICES                                         │
│                                                                           │
│  Cloud Composer 3  │  Vertex AI Pipelines  │  Vertex AI Training          │
│  BigQuery          │  Cloud Storage (GCS)  │  Artifact Registry            │
│  Vertex AI Feature Store (BQ-native v2)    │  Secret Manager               │
│  Vertex AI Model Registry                  │  Vertex AI Endpoints          │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.2 System Interaction Diagram

```
                    ┌─────────────────┐
                    │   Data Scientist │
                    └────────┬────────┘
                             │
                    writes workflow code
                             │
                             ▼
                    ┌─────────────────┐
                    │   Git Push (PR)  │
                    └────────┬────────┘
                             │
                    triggers CI/CD
                             │
                             ▼
              ┌──────────────────────────────┐
              │      GitHub Actions CI/CD     │
              │                              │
              │  1. Lint + Type Check        │
              │  2. Unit Tests               │
              │  3. gml compile --all        │
              │  4. Docker Build + Push      │
              │  5. gml deploy               │
              └──────────┬───────────────────┘
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
   ┌────────────┐  ┌───────────┐  ┌──────────────┐
   │ Artifact   │  │   GCS     │  │   Cloud      │
   │ Registry   │  │  Bucket   │  │  Composer 3  │
   │            │  │           │  │  (Airflow)   │
   │ Docker     │  │ Pipeline  │  │              │
   │ images     │  │ YAMLs     │  │  DAG files   │
   └────────────┘  └───────────┘  └──────┬───────┘
                                         │
                              DAG executes on schedule
                                         │
                         ┌───────────────┼───────────────┐
                         ▼               ▼               ▼
                  ┌────────────┐  ┌────────────┐  ┌────────────┐
                  │  BigQuery  │  │ Vertex AI  │  │   Email /  │
                  │  Operators │  │ Pipeline   │  │   Notify   │
                  │  (SQL/ETL) │  │  Trigger   │  │            │
                  └────────────┘  └─────┬──────┘  └────────────┘
                                        │
                              Vertex AI executes
                              KFP v2 pipeline
                                        │
                         ┌──────────────┼──────────────┐
                         ▼              ▼              ▼
                  ┌────────────┐ ┌────────────┐ ┌────────────┐
                  │  Training  │ │ Evaluation │ │ Deployment │
                  │  (Custom   │ │ (Metrics + │ │ (Endpoint  │
                  │   Job)     │ │  Gate)     │ │  + Model)  │
                  └────────────┘ └────────────┘ └────────────┘
```

### 4.3 CI/CD Workflow Diagram

```
 feature/* branch                    main branch                   v* tag
 ────────────────                    ───────────                   ──────

 git push ───────┐
                 ▼
         ┌───────────────┐
         │   ci.yaml     │
         │               │
         │ • ruff lint    │
         │ • mypy check   │
         │ • unit tests   │
         │ • gml compile  │
         │   --all        │
         │ • docker build │
         │   (no push)    │
         └───────┬───────┘
                 │ pass
                 ▼
         ┌───────────────┐
         │  PR Approved   │
         │  & Merged      │──────────────────┐
         └───────────────┘                   ▼
                                    ┌────────────────┐
                                    │ cd-staging.yaml │
                                    │                │
                                    │ • docker build  │
                                    │   + push (:sha) │
                                    │ • gml compile   │
                                    │   --all         │
                                    │ • gml deploy    │
                                    └────────┬───────┘
                                             │
                                    ┌────────────────┐
                                    │  Create release │
                                    │  tag: v1.2.3    │────────────┐
                                    └────────────────┘             ▼
                                                         ┌────────────────┐
                                                         │  cd-prod.yaml  │
                                                         │                │
                                                         │ • retag docker │
                                                         │   :sha → :v*  │
                                                         │ • gml compile  │
                                                         │   --all        │
                                                         │ • MANUAL GATE  │
                                                         │ • gml deploy   │
                                                         └────────────────┘

 branch deleted ─────────┐
                         ▼
                ┌────────────────┐
                │ teardown.yaml  │
                │                │
                │ • gml teardown │
                │   --branch X   │
                └────────────────┘
```

### 4.4 Environment Isolation

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Git Repository                                │
│                                                                      │
│  feature/add-churn ──→ DEV    (gcp-gap-demo-dev)                    │
│  feature/fix-etl   ──→ DEV    (gcp-gap-demo-dev)     Ephemeral     │
│  hotfix/urgent     ──→ DEV    (gcp-gap-demo-dev)     per-branch    │
│                                                                      │
│  main              ──→ STAGING (gcp-gap-demo-staging) Persistent    │
│                                                                      │
│  v1.0.0            ──→ PROD    (gcp-gap-demo-prod)   Immutable     │
│  v1.1.0            ──→ PROD    (gcp-gap-demo-prod)                  │
└──────────────────────────────────────────────────────────────────────┘

Each environment has completely isolated:
  ✓ GCP Project (separate billing, IAM, quotas)
  ✓ Cloud Composer 3 instance (one per project, shared by all DAGs)
  ✓ BigQuery datasets (namespaced per branch)
  ✓ GCS prefixes (namespaced per branch)
  ✓ Vertex AI experiments, endpoints, models
  ✓ Docker images (same AR repo, different tags)
  ✓ Composer DAG IDs (namespaced prefix)

DEV branches share one Composer 3 instance but get isolated:
  - DAG IDs prefixed with branch namespace
  - BQ datasets separate per branch
  - GCS paths separate per branch
  - Vertex experiments separate per branch
  ➜ Auto-cleaned on branch deletion via teardown workflow
```

---

## 5. Data Scientist Interface

### 5.1 CLI Reference

```
# ── Scaffold ──
gml init project <team> <project>          Scaffold a new project
gml init pipeline <name>                   Scaffold a new use case

# ── Inspect ──
gml context show [--json] [--branch X]     Show resolved environment context

# ── Develop (local iteration) ──
gml run <name> --local                     Run workflow locally (DuckDB stubs)
gml run <name> --local --dry-run           Print execution plan without running
gml run <name> --local --run-date 2026-01-15   Override run date

# ── Compile (generate artifacts) ──
gml compile <name>                         Compile one pipeline/DAG
gml compile --all                          Compile everything

# ── Deploy (push to current environment) ──
gml deploy <name>                          Deploy one pipeline's artifacts
gml deploy --all                           Deploy everything
gml deploy --all --dry-run                 Preview what would be deployed

# ── Cleanup ──
gml teardown --branch <name>               Delete all ephemeral resources for a branch

# ── Debug (advanced) ──
gml run <name> --vertex [--sync]           Submit Vertex pipeline directly (bypass Composer)
```

**Design rationale for the CLI**:

| Decision | Rationale |
|----------|-----------|
| `gml compile` as standalone | Compilation is validation — not a run mode. Data scientists and CI both use it. |
| `gml deploy` unified | Everything is a DAG. One command deploys all artifacts (DAGs + pipeline YAMLs + features). No `deploy dags` vs `deploy features`. |
| `gml deploy <name>` for individual | Data scientists deploying during dev want to deploy just their pipeline, not everything. |
| No `gml promote` | Prod deployment happens via git tags + CI/CD. No manual path to prod. |
| `--vertex` as debug-only | Production path is: merge → CI/CD → Composer. Direct Vertex submission skips orchestration. |

### 5.2 Developer Workflow

```
1. Scaffold:          gml init pipeline my_model
2. Write code:        Edit pipeline.py (or dag.py), sql/, trainer/train.py
3. Test locally:      gml run my_model --local
4. Iterate:           Edit code → gml run --local (repeat)
5. Validate:          gml compile my_model
6. Push PR:           git push → CI validates automatically
7. Merge to main:     CD deploys to staging automatically
8. Verify staging:    Check Composer 3 UI, Vertex AI console
9. Release to prod:   git tag v1.x.x → CD deploys to prod (with approval gate)
```

Steps 6-9 require zero platform knowledge. The data scientist's job ends at step 5.

### 5.3 Directory Structure

```
pipelines/
  {use_case_name}/
  ├── pipeline.py          # Pattern 1: PipelineBuilder (auto-wrapped in DAG)
  │   — OR —
  ├── dag.py               # Pattern 2/3: DAGBuilder (explicit orchestration)
  ├── config.yaml          # Per-use-case config overrides (optional)
  ├── sql/                 # SQL files referenced by sql_file= parameter
  │   ├── extract.sql
  │   └── features.sql
  ├── trainer/             # Training code (ML use cases only)
  │   ├── train.py         # Training script (required)
  │   └── requirements.txt # Python dependencies (required)
  └── seeds/               # Local test data for gml run --local
      └── raw_data.csv
```

**Note**: No `Dockerfile` in the trainer directory. The platform auto-generates Docker images from `train.py` + `requirements.txt` using a base image (see Section 7).

### 5.4 What the Data Scientist Owns vs What the Platform Owns

| Data Scientist | Platform |
|----------------|----------|
| `pipeline.py` or `dag.py` | Dockerfile generation (auto from base image) |
| `sql/*.sql` | Docker image building, tagging, pushing |
| `trainer/train.py` | Compiled DAG files (generated) |
| `trainer/requirements.txt` | Compiled pipeline YAMLs (generated) |
| `config.yaml` | CI/CD workflows |
| `seeds/*.csv` | GCP resource provisioning (Terraform) |
| `feature_schemas/*.yaml` | Deployment to Composer 3 |
| Git tags for releases | Environment isolation + teardown |

---

## 6. Three Toy Use Cases

### 6.1 Churn Prediction — Pure ML

**Pattern**: `pipeline.py` only → auto-wrapped in single-task Composer DAG

```python
# pipelines/churn_prediction/pipeline.py
from gcp_ml_framework.pipeline import PipelineBuilder
from gcp_ml_framework.components.ingestion import BigQueryExtract
from gcp_ml_framework.components.transformation import BQTransform
from gcp_ml_framework.components.ml import TrainModel, EvaluateModel, DeployModel

pipeline = (
    PipelineBuilder(name="churn_prediction", schedule="0 6 * * 1")
    .ingest(BigQueryExtract(
        query="SELECT user_id, event_type, event_date, session_duration "
              "FROM `{bq_dataset}.raw_events` "
              "WHERE event_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)",
        output_table="raw_events",
    ))
    .transform(BQTransform(sql_file="sql/features.sql", output_table="features"))
    .train(TrainModel(
        machine_type="n2-standard-8",
        hyperparameters={"learning_rate": 0.05, "n_estimators": 300},
    ))
    .evaluate(EvaluateModel(metrics=["auc", "f1"], gate={"auc": 0.78}))
    .deploy(DeployModel(machine_type="n2-standard-4", min_replicas=1, max_replicas=3))
    .build()
)
```

**What `gml compile` generates**:
1. `compiled_pipelines/churn_prediction.yaml` — KFP v2 pipeline definition
2. `dags/{namespace}__churn_prediction.py` — Airflow DAG with one VertexPipelineTask

**How Docker works** (zero DS involvement):
- CI/CD detects `pipelines/churn_prediction/trainer/` exists
- Auto-generates Dockerfile from `base-ml` image + `requirements.txt`
- Builds and pushes: `{ar_host}/{project}/{namespace}/churn-prediction-trainer:{tag}`
- Framework resolves the full image URI at compile time into the KFP YAML

**Data scientist provides**: `trainer/train.py`, `trainer/requirements.txt`, `sql/features.sql`, `seeds/raw_events.csv`
**Platform handles**: Dockerfile, Docker build, image push, DAG generation, pipeline compilation, deployment

### 6.2 Sales Analytics — Non-ML, Non-Linear DAG

**Pattern**: `dag.py` with parallel branches, fan-out, fan-in

```python
# pipelines/sales_analytics/dag.py
from gcp_ml_framework.dag import DAGBuilder
from gcp_ml_framework.dag.tasks import BQQueryTask, EmailTask

dag = (
    DAGBuilder(name="sales_analytics", schedule="30 7 * * *")
    # Three independent extracts (run in parallel — depends_on=[])
    .task(BQQueryTask(sql_file="sql/extract_orders.sql",
                      destination_table="raw_orders"),
          name="extract_orders", depends_on=[])
    .task(BQQueryTask(sql_file="sql/extract_inventory.sql",
                      destination_table="raw_inventory"),
          name="extract_inventory", depends_on=[])
    .task(BQQueryTask(sql_file="sql/extract_returns.sql",
                      destination_table="raw_returns"),
          name="extract_returns", depends_on=[])

    # Three transforms (each depends on its extract)
    .task(BQQueryTask(sql_file="sql/agg_revenue.sql",
                      destination_table="daily_revenue"),
          name="agg_revenue", depends_on=["extract_orders"])
    .task(BQQueryTask(sql_file="sql/check_stock.sql",
                      destination_table="stock_alerts"),
          name="check_stock", depends_on=["extract_inventory"])
    .task(BQQueryTask(sql_file="sql/agg_refunds.sql",
                      destination_table="daily_refunds"),
          name="agg_refunds", depends_on=["extract_returns"])

    # Fan-in: report depends on all three transforms
    .task(BQQueryTask(sql_file="sql/build_report.sql",
                      destination_table="daily_report"),
          name="build_report",
          depends_on=["agg_revenue", "check_stock", "agg_refunds"])
    .task(EmailTask(to=["analytics@company.com"],
                    subject="Daily sales report ready — {run_date}"),
          name="notify", depends_on=["build_report"])
    .build()
)
```

**DAG shape** (non-linear):
```
extract_orders ────→ agg_revenue ────→┐
extract_inventory ─→ check_stock ────→├→ build_report → notify
extract_returns ───→ agg_refunds ───→┘
```

**Key demonstrations**: Parallel task execution, per-task dependencies, fan-out/fan-in pattern. No Docker, no Vertex AI — pure Airflow operators.

### 6.3 Recommendation Engine — Hybrid (Two Vertex Pipelines)

**Pattern**: `dag.py` with DAGBuilder containing two VertexPipelineTasks

```python
# pipelines/recommendation_engine/dag.py
from gcp_ml_framework.pipeline import PipelineBuilder
from gcp_ml_framework.dag import DAGBuilder
from gcp_ml_framework.dag.tasks import BQQueryTask, VertexPipelineTask, EmailTask
from gcp_ml_framework.components.ingestion import BigQueryExtract
from gcp_ml_framework.components.transformation import BQTransform
from gcp_ml_framework.components.feature_store import WriteFeatures, ReadFeatures
from gcp_ml_framework.components.ml import TrainModel, EvaluateModel, DeployModel

# --- Vertex Pipeline 1: Feature Engineering ---
feature_pipeline = (
    PipelineBuilder(name="reco_features")
    .ingest(BigQueryExtract(
        query="SELECT user_id, item_id, interaction_type, ts "
              "FROM `{bq_dataset}.raw_interactions`",
        output_table="raw_interactions",
    ))
    .transform(BQTransform(sql_file="sql/user_features.sql", output_table="user_features"))
    .transform(BQTransform(sql_file="sql/item_features.sql", output_table="item_features"))
    .write_features(WriteFeatures(entity="user", feature_group="behavioral"))
    .build()
)

# --- Vertex Pipeline 2: Model Training (uses output from Pipeline 1) ---
training_pipeline = (
    PipelineBuilder(name="reco_training")
    .read_features(ReadFeatures(
        entity="user",
        features=["session_count_7d", "total_purchases_30d", "avg_session_duration_s"],
    ))
    .train(TrainModel(
        machine_type="n2-standard-16",
        hyperparameters={"embedding_dim": 64, "epochs": 50},
    ))
    .evaluate(EvaluateModel(metrics=["ndcg@10", "map@10"], gate={"ndcg@10": 0.35}))
    .deploy(DeployModel(machine_type="n2-standard-4"))
    .build()
)

# --- Orchestration DAG ---
dag = (
    DAGBuilder(name="recommendation_engine", schedule="0 2 * * *")
    .task(BQQueryTask(sql_file="sql/extract_interactions.sql",
                      destination_table="raw_interactions"),
          name="extract_data")
    .task(VertexPipelineTask(pipeline=feature_pipeline),
          name="compute_features", depends_on=["extract_data"])
    .task(VertexPipelineTask(pipeline=training_pipeline),
          name="train_model", depends_on=["compute_features"])
    .task(EmailTask(to=["ml-team@company.com"],
                    subject="Recommendation model updated — {run_date}"),
          name="notify", depends_on=["train_model"])
    .build()
)
```

**Flow**:
```
Composer DAG:  extract_data → compute_features → train_model → notify
                                    │                  │
                              Vertex Pipeline 1   Vertex Pipeline 2
                              (reco_features)     (reco_training)
                                    │                  │
                              ingest → transform  read_features → train
                              → transform →       → evaluate → deploy
                              write_features
```

**Key demonstrations**: DAG orchestrates two separate Vertex AI pipelines sequentially. Output of Pipeline 1 (features in BQ/Feature Store) feeds Pipeline 2. Mixed task types: BQ operator + Vertex triggers + email. Two auto-generated Docker images, two KFP YAMLs, one Airflow DAG file.

---

## 7. Docker Strategy — Fully Automated

### 7.1 Zero-Dockerfile Experience

Data scientists **never write Dockerfiles**. The platform auto-generates container images:

**What the data scientist provides**:
```
trainer/
  train.py              # Training script (entrypoint)
  requirements.txt      # Python dependencies
```

**What the platform does** (in CI/CD):
1. Detects `trainer/` directory in a pipeline
2. Auto-generates a Dockerfile:
   ```dockerfile
   FROM {ar_host}/{project}/base/base-ml:{base_version}
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   ENTRYPOINT ["python", "train.py"]
   ```
3. Builds the image
4. Tags and pushes to Artifact Registry

**Escape hatch**: If a data scientist needs a custom Dockerfile (e.g., system packages, non-Python deps), they can place a `Dockerfile` in `trainer/`. If present, the platform uses it instead of auto-generating. This is the exception, not the norm.

### 7.2 How TrainModel Resolves Images

`TrainModel` does **not** require a `trainer_image` parameter. The framework derives it:

```python
# Image name derived from pipeline name:
#   pipeline name: "churn_prediction" → image: "churn-prediction-trainer"
#
# Full URI resolved at compile time:
#   {ar_host}/{project}/{namespace}/churn-prediction-trainer:{tag}
#
# Tag determined by environment:
#   DEV:     dev-{git_sha_short}
#   STAGING: {git_sha_short}
#   PROD:    {git_tag}  (e.g., v1.2.0)

TrainModel(machine_type="n2-standard-8", hyperparameters={...})
# Image URI is auto-resolved — no trainer_image needed
```

If a pipeline needs a **custom image name** (rare), it can override:
```python
TrainModel(trainer_image="my-special-trainer", machine_type="n2-standard-8")
```

### 7.3 Base Images (Platform-Owned)

```
docker/base/
  base-python/Dockerfile    # python:3.11-slim + common utilities
  base-ml/Dockerfile        # FROM base-python + numpy, pandas, scikit-learn, xgboost, lightgbm
```

Stored in AR: `{ar_host}/{project}/base/base-python:{version}`, `{ar_host}/{project}/base/base-ml:{version}`

Semantic versioned: MAJOR = Python version change, MINOR = dependency updates. Rebuilt via CI when `docker/base/` files change.

### 7.4 Tagging Rules

| Environment | Tag Format | Example |
|-------------|-----------|---------|
| DEV | `dev-{sha}` | `dev-a1b2c3d` |
| STAGING | `{sha}` | `a1b2c3d` |
| PROD | `v{semver}` | `v1.2.0` |

- **Never use `:latest` for project images** — mutable and non-reproducible
- Each image carries OCI labels: `org.opencontainers.image.revision`, `org.opencontainers.image.source`, `org.opencontainers.image.created`
- AR cleanup policies: untagged images after 7 days, `dev-*` tags after 30 days, `v*` tags retained indefinitely

### 7.5 Serving Containers

For `DeployModel`, the framework uses Google's pre-built serving containers. These are referenced by their path-versioned URI:

```python
# Google's pre-built containers are versioned by path segment (e.g., "1-3" = sklearn 1.3).
# The :latest tag on these is stable and maintained by Google — this is their documented pattern.
# This is the ONE exception to our "no :latest" rule.
DeployModel(
    serving_container="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest",
)
```

If no `serving_container` is specified, the framework defaults based on the training framework detected in `requirements.txt` (sklearn → sklearn serving container, tensorflow → tf serving container).

---

## 8. Local Execution Semantics

### 8.1 `gml run <name> --local`

Local runs validate logic without touching GCP. The framework substitutes local equivalents:

| Production | Local Substitute |
|-----------|-----------------|
| BigQuery | DuckDB (in-process, SQL-compatible) |
| GCS | Local `local_output/{name}/` directory |
| Vertex AI Training | Direct `python trainer/train.py` execution (no Docker) |
| Vertex AI Endpoints | Skipped (prints "would deploy to endpoint X") |
| Email notifications | Printed to console (recipients, subject, body) |
| Airflow macros (`{{ ds }}`) | Resolved from `--run-date` flag or today's date |
| Feature Store writes | Write to local DuckDB table |
| Feature Store reads | Read from local DuckDB table |

### 8.2 Local Execution for Pipelines (PipelineBuilder)

1. Load seed data from `seeds/` into DuckDB
2. Execute steps sequentially (topological order)
3. Each component's `local_run(context, **kwargs)` is called
4. SQL operations use BQ→DuckDB translation (`sql_compat.py`)
5. TrainModel runs `trainer/train.py` directly as a subprocess (no Docker)
6. EvaluateModel computes real metrics against local model + seed data
7. DeployModel is skipped (logged as "would deploy")
8. Outputs written to `local_output/{pipeline_name}/`

### 8.3 Local Execution for DAGs (DAGBuilder)

1. Load seed data from `seeds/` into DuckDB
2. Compute topological order of all tasks
3. Execute tasks **sequentially in topological order** — parallel branches run one at a time but in a valid dependency order
4. Per task type:
   - **BQQueryTask** → run SQL via DuckDB (with `sql_compat` translation). Load `sql_file` from disk.
   - **EmailTask** → print to console: recipients, subject, resolved body
   - **VertexPipelineTask** → run the contained `PipelineDefinition` locally via the pipeline LocalRunner (recursive)
5. Simulated Airflow context:
   - `{run_date}` → from `--run-date` flag or today (YYYY-MM-DD)
   - `{bq_dataset}` → local DuckDB database name
   - `{namespace}` → resolved from current git branch
   - `{gcs_prefix}` → `local_output/{pipeline_name}/`

### 8.4 `--dry-run` Mode

`gml run <name> --local --dry-run` prints the execution plan without running:
```
Pipeline: churn_prediction
  Step 1: ingest_raw_events (BigQueryExtract) — query: SELECT ...
  Step 2: engineer_features (BQTransform) — sql_file: sql/features.sql
  Step 3: train_churn_model (TrainModel) — machine_type: n2-standard-8
  Step 4: evaluate_model (EvaluateModel) — gate: {auc: 0.78}
  Step 5: deploy_churn_model (DeployModel) — [skipped locally]
```

**Design note**: Local runs are for **logic validation**, not performance testing. Parallel branches execute sequentially. This is intentional — the local runner validates the dependency graph and data flow, not parallelism.

---

## 9. Nomenclature & Versioning

### 9.1 Resource Naming Convention

All names derived from `{team}-{project}-{branch}`. No hardcoded identifiers anywhere.

**Branch name sanitization rules**:
- `branch_safe` (for namespaces, hyphens): lowercase, replace `/` and `.` with `-`, truncate to 30 chars
- `branch_bq` (for BigQuery, underscores): lowercase, replace `/`, `.`, `-` with `_`, truncate to 30 chars
- GCS paths: use original branch string as-is (e.g., `v1.0.0` stays `v1.0.0`)

Examples use `team=dsci`, `project=examplechurn`.

| Resource | Pattern | Dev (`feature/xyz`) | Prod (`v1.0.0`) |
|----------|---------|---------------------|-----------------|
| **Namespace** | `{team}-{project}-{branch_safe}` | `dsci-examplechurn-feature-xyz` | `dsci-examplechurn-v1-0-0` |
| **BQ Dataset** | `{team}_{project}_{branch_bq}` | `dsci_examplechurn_feature_xyz` | `dsci_examplechurn_v1_0_0` |
| **GCS Prefix** | `gs://{team}-{project}/{branch}/` | `gs://dsci-examplechurn/feature-xyz/` | `gs://dsci-examplechurn/v1.0.0/` |
| **DAG ID** | `{namespace_bq}__{dag_name}` | `dsci_examplechurn_feature_xyz__churn_prediction` | `dsci_examplechurn_v1_0_0__churn_prediction` |
| **Vertex Experiment** | `{namespace}-{pipeline}-exp` | `dsci-examplechurn-feature-xyz-churn-exp` | — |
| **Vertex Endpoint** | `{namespace}--{pipeline}--endpoint` | `dsci-examplechurn-feature-xyz--churn--ep` | `dsci-examplechurn-v1-0-0--churn--ep` |
| **Model Name** | `{namespace}--{pipeline}--model` | Auto-versioned in Model Registry | |
| **Docker Image** | `{ar}/{project}/{namespace}/{name}-trainer` | `:dev-a1b2c3d` | `:v1.0.0` |
| **Pipeline YAML** | `gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml` | `.../feature-xyz/pipelines/...` | `.../v1.0.0/pipelines/...` |

### 9.2 Artifact Versioning

| Artifact | Location | Versioning | Lifecycle |
|----------|----------|------------|-----------|
| **Pipeline YAML** | `gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml` | Overwritten per deploy; GCS object versioning for history | Cleaned with branch teardown (dev) |
| **Model** | Vertex AI Model Registry | Auto-incremented version per model display name | Retained indefinitely |
| **Docker Image** | Artifact Registry | Git SHA (dev/staging) / semver (prod) | Cleanup policies (see 7.4) |
| **DAG File** | Composer 3 GCS bucket `dags/` folder | Overwritten on deploy; git is the audit trail | Cleaned with branch teardown (dev) |
| **Feature Schema** | `feature_schemas/*.yaml` in repo | Git history | — |
| **SQL Files** | `pipelines/{name}/sql/` in repo | Git history | — |

### 9.3 Version Bumping

**Automatic** (zero DS action):
- Docker image tags → derived from git SHA or release tag
- Pipeline YAML → recompiled on every deploy
- DAG files → regenerated on every deploy
- Model versions → auto-incremented by Vertex AI Model Registry

**Manual** (DS decision):
- Release tags (`v1.0.0` → `v1.1.0`) → created when ready to promote to prod
- Base image versions → platform team bumps when dependencies change

**Semantic version rules for release tags**:
- PATCH: Hyperparameter tweak, config change, no pipeline structure change
- MINOR: New pipeline step, model architecture change, new features added
- MAJOR: Breaking change (endpoint contract, entity schema change)

---

## 10. Pipeline Interface Contract

### 10.1 File Rules

Each pipeline directory (`pipelines/{name}/`) must contain **exactly one** of:
- `pipeline.py` — defines a `PipelineDefinition` via `PipelineBuilder.build()`
- `dag.py` — defines a `DAGDefinition` via `DAGBuilder.build()`

Having both is a **hard error** at compile time. Having neither is also a hard error.

The module-level variable must be named `pipeline` (for `pipeline.py`) or `dag` (for `dag.py`). The compiler imports and reads this variable.

### 10.2 Template Macros

SQL files and string parameters support these template macros, resolved at **compile time**:

| Macro | Resolves To | Example |
|-------|------------|---------|
| `{bq_dataset}` | Namespaced BQ dataset | `dsci_examplechurn_feature_xyz` |
| `{namespace}` | Full namespace | `dsci-examplechurn-feature-xyz` |
| `{gcs_prefix}` | GCS path prefix | `gs://dsci-examplechurn/feature-xyz/` |
| `{run_date}` | Airflow execution date | Becomes `{{ ds }}` in generated DAG |
| `{artifact_registry}` | AR host + project | `us-central1-docker.pkg.dev/gcp-gap-demo-staging` |

**Rules**:
- Framework macros use `{single_braces}` — resolved at compile time
- Airflow macros use `{{ double_braces }}` — resolved at DAG runtime by Airflow
- The compiler translates `{run_date}` to `{{ ds }}` in generated DAG files
- Macros in SQL files are resolved when the file is loaded by the compiler

### 10.3 SQL File Convention

- SQL files live in `pipelines/{name}/sql/`
- Referenced by `sql_file="sql/filename.sql"` (relative to the pipeline directory)
- Use **explicit column selection** — avoid `SELECT *` (schema drift breaks models silently)
- Template macros are available in SQL files

### 10.4 Output Table Naming

`destination_table` in tasks refers to a table within the pipeline's namespaced BQ dataset:
- Specified as bare name: `destination_table="raw_orders"` → `{bq_dataset}.raw_orders`
- The dataset prefix is applied automatically by the compiler

---

## 11. Framework Distribution to Composer

### 11.1 Key Design: Generated DAGs Are Self-Contained

Generated Airflow DAG files import **only** from standard Airflow and `apache-airflow-providers-google`. There are **no `gcp_ml_framework` imports** at Airflow parse time. All framework-specific values (namespace, dataset, GCS paths, image URIs) are **resolved at compile time** and baked into the generated Python file.

This means:
- **Composer does not need `gcp_ml_framework` installed**
- **Composer does not need `kfp` installed**
- Composer uses only its pre-installed packages (`apache-airflow-providers-google` is pre-installed on Composer 3)
- The framework runs in CI/CD and on developer machines — never inside Composer

### 11.2 What a Generated DAG File Looks Like

```python
# Auto-generated by gml compile — do not edit
# Source: pipelines/churn_prediction/pipeline.py
# Compiled: 2026-03-05T14:30:00Z | Branch: main | SHA: a1b2c3d

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.google.cloud.operators.vertex_ai.pipeline_job import (
    CreatePipelineJobOperator,
)

_default_args = {
    "owner": "dsci-examplechurn",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
}

with DAG(
    dag_id="dsci_examplechurn_main__churn_prediction",
    schedule="0 6 * * 1",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["dsci", "examplechurn", "main"],
    default_args=_default_args,
) as dag:

    run_churn_pipeline = CreatePipelineJobOperator(
        task_id="run_churn_prediction",
        project_id="gcp-gap-demo-staging",
        location="us-central1",
        display_name="churn_prediction_{{ ds_nodash }}",
        template_path="gs://dsci-examplechurn/main/pipelines/churn_prediction/pipeline.yaml",
        pipeline_root="gs://dsci-examplechurn/main/pipeline_runs/churn_prediction/",
        parameter_values={},
        labels={"namespace": "dsci-examplechurn-main", "pipeline": "churn-prediction"},
    )
```

No framework code. No KFP imports. Pure Airflow. Fast DAG parsing.

### 11.3 VertexPipelineTask → CreatePipelineJobOperator

When the compiler encounters a `VertexPipelineTask(pipeline=some_pipeline_def)`:
1. Compiles the `PipelineDefinition` to KFP v2 YAML
2. Writes YAML to `compiled_pipelines/{vp_name}.yaml`
3. Generates a `CreatePipelineJobOperator` in the DAG file that references the YAML at its GCS path
4. All values (project_id, location, template_path, pipeline_root) are baked in at compile time

The `template_path` follows the canonical pattern: `gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml`

---

## 12. CI/CD Design

### 12.1 Four Workflows

#### `ci.yaml` — On every pull request

```yaml
# Trigger: pull_request (opened, synchronize, reopened)
# Duration: ~3-5 min

steps:
  - checkout
  - setup python 3.11 + uv
  - uv sync
  - ruff check + ruff format --check
  - mypy --strict gcp_ml_framework/
  - pytest tests/unit/ -v
  - gml compile --all
  - for each pipeline with trainer/:
      docker build (verify Dockerfile generates and builds — no push)
```

#### `cd-staging.yaml` — On merge to main

```yaml
# Trigger: push to main
# Auth: Workload Identity Federation → staging GCP project
# Duration: ~5-10 min

steps:
  - checkout
  - authenticate to GCP (WIF)
  - setup python 3.11 + uv

  # Docker: auto-generate Dockerfiles, build, push with SHA tag
  - for each pipeline with trainer/:
      auto-generate Dockerfile from base-ml + requirements.txt
      docker build + tag {ar_host}/{staging_project}/{namespace}/{name}-trainer:{sha}
      docker push

  # Compile + Deploy
  - GML_ENV_OVERRIDE=STAGING gml compile --all
  - GML_ENV_OVERRIDE=STAGING gml deploy --all
```

#### `cd-prod.yaml` — On release tag

```yaml
# Trigger: push tag matching v*
# Auth: Workload Identity Federation → prod GCP project
# Environment: "production" (requires manual approval in GitHub)
# Duration: ~5 min

steps:
  - checkout at tag
  - authenticate to GCP (WIF, prod project)

  # Docker: retag staging images with semver (don't rebuild)
  - for each pipeline with trainer/:
      pull {ar_host}/{staging_project}/{namespace}/{name}-trainer:{sha}
      tag  {ar_host}/{prod_project}/{namespace}/{name}-trainer:{tag_name}
      push to prod AR

  # Compile + Deploy (prod config)
  - GML_ENV_OVERRIDE=PROD gml compile --all
  - GML_ENV_OVERRIDE=PROD gml deploy --all
```

**Prod deploys only via tags. No manual `gml deploy` to prod. CI/CD is the only path.**

#### `teardown.yaml` — On branch delete

```yaml
# Trigger: delete event (branch)
# Auth: WIF → dev GCP project
# Duration: ~2 min

steps:
  - authenticate to GCP (WIF, dev project)
  - GML_ENV_OVERRIDE=DEV gml teardown --branch {deleted_branch} --confirm
```

### 12.2 What `gml compile` Does

```
gml compile <name>      Compile one pipeline/DAG
gml compile --all       Compile everything

For pipeline.py (PipelineBuilder):
  1. Import pipeline.py, read the `pipeline` variable
  2. Compile PipelineDefinition → KFP v2 YAML
     → compiled_pipelines/{name}.yaml
  3. Auto-wrap in DAG: generate Airflow DAG file with single CreatePipelineJobOperator
     → dags/{namespace}__{name}.py

For dag.py (DAGBuilder):
  1. Import dag.py, read the `dag` variable
  2. Generate Airflow DAG file with all tasks wired
     → dags/{namespace}__{name}.py
  3. For each VertexPipelineTask in the DAG:
     Compile its PipelineDefinition → KFP v2 YAML
     → compiled_pipelines/{vp_name}.yaml

Output directories (both gitignored):
  compiled_pipelines/*.yaml    KFP v2 pipeline definitions
  dags/*.py                    Airflow DAG files
```

### 12.3 What `gml deploy` Does

```
gml deploy <name>       Deploy one pipeline's artifacts
gml deploy --all        Deploy all artifacts
gml deploy --dry-run    Preview only

Steps:
  1. Compile (if not already compiled — calls gml compile internally)
  2. Upload compiled pipeline YAMLs to GCS:
     gs://{bucket}/{branch}/pipelines/{name}/pipeline.yaml
  3. Upload DAG files to Composer 3 GCS bucket:
     {composer_dags_path}/{namespace}__{name}.py
  4. Deploy feature schemas (create/update FeatureGroups + FeatureViews)

Single-pipeline deploy (gml deploy churn_prediction):
  Only uploads that pipeline's DAG file and YAML. Does not touch other pipelines.
```

---

## 13. Feature Store Design (BQ-Native v2)

### 13.1 Architecture

```
Data Scientist writes SQL                Platform handles
─────────────────────────                ────────────────

BQTransform(sql_file="sql/              BQ Table: {dataset}.user_features
  user_features.sql",                        │
  output_table="user_features")              │ gml deploy registers as FeatureGroup
                                             ▼
                                        Vertex AI Feature Store v2
                                             │
                                             │ FeatureView + scheduled sync
                                             ▼
                                        Bigtable Online Store
                                             │
                                             │ Serving API (< 2ms p99)
                                             ▼
                                        Prediction Service
```

### 13.2 Key Principle

**BQ tables ARE the offline feature store.** No separate ingestion step. The `BQTransform` component writes to BQ — that IS the feature data. The platform registers those tables as FeatureGroups and sets up online serving via `gml deploy`.

### 13.3 Components

- **WriteFeatures** → registers a BQ table as a FeatureGroup (metadata operation — no data movement)
- **ReadFeatures** → reads from BQ (offline, for training) or Feature Store serving API (online, for inference)
- **`gml deploy`** → creates/updates FeatureGroups + FeatureViews from `feature_schemas/*.yaml`

### 13.4 Timeline

- Feature Store v1: sunsetting May 2026 (no new features), full shutdown Feb 2027
- Feature Store v2 (BQ-native): current GA, recommended for all new implementations

---

## 14. Infrastructure (Terraform)

### 14.1 Structure

```
terraform/
  modules/
    composer/            Cloud Composer 3 environment
    artifact_registry/   Docker repos (base + per-team)
    iam/                 Service accounts + Workload Identity Federation
    storage/             GCS buckets (one per team-project)
  envs/
    dev/main.tf + terraform.tfvars
    staging/main.tf + terraform.tfvars
    prod/main.tf + terraform.tfvars
  backend.tf             GCS remote state
```

### 14.2 What Terraform Manages vs What the Framework Manages

| Terraform (long-lived, shared) | Framework (ephemeral, per-branch) |
|-------------------------------|----------------------------------|
| Cloud Composer 3 environments | BQ datasets |
| Artifact Registry repos | GCS prefixes within buckets |
| GCS buckets | Vertex AI experiments, endpoints, models |
| IAM roles + service accounts | Composer DAG files |
| Workload Identity Federation | Feature Store resources |

---

## 15. Framework Config Reference

```yaml
# framework.yaml
team: dsci                                    # Team identifier (required)
project: examplechurn                         # Project identifier (required)

gcp:
  dev_project_id: gcp-gap-demo-dev            # GCP project for DEV (required)
  staging_project_id: gcp-gap-demo-staging    # GCP project for STAGING (required)
  prod_project_id: gcp-gap-demo-prod          # GCP project for PROD (required)
  region: us-central1                         # GCP region
  artifact_registry_host: us-central1-docker.pkg.dev
  service_account_email:                      # Optional — derived if empty

  # Composer 3 DAGs folder path (discovered from Composer API or set manually)
  # This is the full path including /dags — the framework uploads directly to this path
  composer_dags_path:
    dev: gs://us-central1-dsci-examplechurn-dev-XXXXX-bucket/dags
    staging: gs://us-central1-dsci-examplechurn-staging-XXXXX-bucket/dags
    prod: gs://us-central1-dsci-examplechurn-prod-XXXXX-bucket/dags

feature_store:
  online_serving_type: bigtable               # bigtable (recommended)
  sync_schedule: "0 */6 * * *"                # Feature sync cron

secrets:
  secret_prefix:                              # Defaults to namespace

docker:
  base_image: base-ml                         # Default base image for auto-generated Dockerfiles
  base_version: "1.0"                         # Base image version
```

---

## 16. Gap Analysis

### What We Have (Solid Foundation — ~2,960 LOC, 167 tests)

| Component | Status | Notes |
|-----------|--------|-------|
| Naming, Config, Context, Secrets | Production-ready | Fully tested, frozen dataclasses |
| PipelineBuilder + Compiler + Runner | Production-ready | Fluent DSL, KFP v2 YAML output |
| DAGBuilder + Compiler + Tasks | Production-ready | Fluent DSL, Airflow code output |
| DAG factory (auto-discovery) | Working | Handles both pipeline.py and dag.py |
| Feature schemas (YAML) | Production-ready | YAML → typed dataclasses |
| CLI (8 commands) | Working | All implemented, none tested |
| Example: churn_prediction | Working | PipelineBuilder pattern |
| Example: daily_sales_etl | Working | DAGBuilder pattern (linear) |

### Gaps (Ordered by Priority)

| # | Gap | Effort | Description |
|---|-----|--------|-------------|
| 1 | **Restructure CLI** | Small | Add `gml compile`, unify `gml deploy`, remove `gml promote`, support `<name>` and `--all` |
| 2 | **CI/CD workflows** | Medium | 4 GitHub Actions files |
| 3 | **Docker auto-generation** | Small | Auto-Dockerfile from base image + requirements.txt in CI |
| 4 | **Docker base images** | Small | `docker/base/` with base-python and base-ml |
| 5 | **TrainModel auto-image resolution** | Small | Derive image name from pipeline name, resolve full URI at compile |
| 6 | **`sql_file` support in BQQueryTask** | Small | Load SQL from file at compile time |
| 7 | **VertexPipelineTask accepts PipelineDefinition** | Small | Takes builder output, handles compilation internally |
| 8 | **Use case: sales_analytics** | Small | Non-linear DAG (8 tasks, fan-out/fan-in) |
| 9 | **Use case: recommendation_engine** | Medium | Hybrid DAG (2 Vertex pipelines, trainer, seeds) |
| 10 | **Update churn_prediction** | Small | Remove explicit trainer_image, verify auto-wrap, update machine types |
| 11 | **Terraform modules** | Medium | Composer 3, AR, IAM, storage |
| 12 | **Feature Store v2 migration** | Medium | Rewrite client.py for BQ-native APIs |
| 13 | **Model versioning** | Small | Versioned GCS paths + Model Registry in TrainModel |
| 14 | **Experiment tracking** | Small | `aiplatform.log_metrics()` in EvaluateModel |
| 15 | **Fix teardown** | Small | Delete Vertex experiments, endpoints, models, DAGs |
| 16 | **Fix EvaluateModel.local_run()** | Small | Real metrics, not `random.uniform()` |
| 17 | **Remove dead code** | Small | `as_airflow_operator()`, PandasTransform, composer naming methods |
| 18 | **Local DAG runner** | Medium | Implement local DAG execution (topological order, stubs) |
| 19 | **Update dependencies** | Small | Bump to latest SDK versions per Section 2 |
| 20 | **Pipeline interface enforcement** | Small | Hard error if both pipeline.py and dag.py exist |
| 21 | **Component tests** | Medium | All 8 components |
| 22 | **CLI tests** | Medium | All CLI commands |
| 23 | **Integration tests** | Large | E2E compile + local run for all 3 use cases |

---

## 17. Implementation Roadmap

Phases are ordered by dependency — each phase builds on the prior. Please proceed by Phases. See `docs/planning/next_steps.md` for detailed, implementable instructions per phase.

### Phase 1: Clean Foundation

Remove dead code, fix broken things, restructure CLI, update core interfaces. Establishes the correct contracts before building on top.

### Phase 2: Three Use Cases + Docker Automation + Local DAG Runner

Build the three toy use cases, Docker auto-generation, TrainModel auto-image resolution, and the local DAG runner. Proves the platform works end-to-end locally.

### Phase 3: Feature Store + Model Management

Rewrite Feature Store client for v2 BQ-native APIs. Add model versioning and experiment tracking.

### Phase 4: Infrastructure (Terraform)

Terraform modules for Composer 3, Artifact Registry, IAM, storage. Per-environment configs.

### Phase 5: Testing

Component tests, CLI tests, integration tests. All three use cases verified E2E.

### Phase 6: CI/CD

GitHub Actions workflows (ci, cd-staging, cd-prod, teardown). Full automated pipeline from PR to production. This is last because it depends on all other phases being stable.

---

## Appendix A: Design Decisions

| Decision | Rationale | Alternative Rejected |
|----------|-----------|---------------------|
| Everything is a DAG | One scheduling system, one monitoring surface, one deploy mechanism | Separate Vertex-only and Composer-only paths (splits interface) |
| Auto-wrap pipeline.py in DAG | Minimal friction for pure ML. DS who only do ML never learn DAGBuilder. | Require dag.py for everything (unnecessary boilerplate) |
| PipelineBuilder + DAGBuilder separate | Different domains, different outputs (KFP YAML vs Airflow Python) | Unified "WorkflowBuilder" (over-abstraction, hides cost implications) |
| Zero-Dockerfile experience | DS write code, not infra. Docker is a platform concern. | Require Dockerfile (friction, error-prone, DS shouldn't need to know Docker) |
| Generated DAGs are self-contained | Composer doesn't need framework installed. Fast DAG parsing. No coupling. | Install framework in Composer (dependency conflicts, parse overhead) |
| Composer 3 | Serverless, simplified ops, Composer 2 EOL Sep 2026 | Composer 2 (approaching end of life) |
| Tag-based prod, no `gml promote` | Only CI/CD deploys to prod. Removes manual error path. | Manual promote (unauthorized prod deploys risk) |
| Unified `gml deploy` | Everything is a DAG — DAGs, pipelines, features are one deployment unit | Separate `deploy dags` / `deploy features` (false separation) |
| `gml compile` standalone | Compilation is validation. DS and CI both use it independently. | `gml run --compile-only` (conflates running with compiling) |
| `gml deploy <name>` + `--all` | DS deploys their pipeline during dev; CI deploys everything | Only `--all` (can't deploy individually during development) |
| Git SHA tags for dev/staging | Automatic, traceable, zero manual bumping | Semver everywhere (manual friction) |
| One Composer 3 per project | DCU billing makes shared instance cost-effective. Branch isolation via DAG ID prefix. | Per-branch Composer (expensive, unnecessary) |
| BQ-native Feature Store v2 | BQ tables = offline store. No gRPC hacks. v1 sunsetting. | Fix v1 (fundamentally slower, approaching EOL) |
| Terraform for shared infra only | Ephemeral resources don't benefit from state management | Terraform for everything (overhead for per-branch resources) |
| N2/C3 machine types | Current-gen, 20%+ better perf. N1 is legacy. | N1-standard (outdated) |

## Appendix B: Dependencies (pyproject.toml)

These are for the **framework's development and CI/CD environment**. Composer 3 has its own managed runtime — generated DAG files only import from `airflow` and `airflow.providers.google`, both pre-installed.

```toml
[project]
name = "gcp-ml-framework"
version = "0.2.0"
requires-python = ">=3.11"
dependencies = [
    "kfp>=2.15,<3",
    "google-cloud-aiplatform>=1.136",
    "google-cloud-bigquery>=3.25",
    "google-cloud-storage>=2.18",
    "google-cloud-secret-manager>=2.21",
    "apache-airflow>=2.10",
    "apache-airflow-providers-google>=20.0",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "typer>=0.15",
    "rich>=13",
    "pyyaml>=6",
    "duckdb>=1.1",
    "pyarrow>=18",
    "pandas>=2.2",
]
```

> **Note on Composer compatibility**: The `>=` ranges are for our CI/CD environment. Composer 3 manages its own Airflow + providers versions. Since generated DAGs import only from standard Airflow (no framework imports), there is no version conflict between our framework and Composer's runtime.
