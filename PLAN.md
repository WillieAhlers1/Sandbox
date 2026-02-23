# GCP ML Framework — Implementation Plan

> **Status:** Draft — awaiting review before implementation begins.

---

## 1. Vision & Guiding Principles

This framework lets data scientists and analysts define ML pipelines as Python code, run them locally for iteration, and promote them to GCP with a single command. Every GCP resource name encodes its origin: `{team}-{project}-{branch}`. No tagging required—names *are* the metadata.

| Principle | What it means in practice |
|---|---|
| **Branch-based isolation** | Each git branch gets its own GCS prefix, BQ dataset, Vertex experiment, and Feature Store entity namespace. `main`/`prod` is just another branch with promotion gates. |
| **Feature Store foundation** | Feature data is organized around business *entities* (User, Item, Session…). All transformation outputs write entity-keyed feature groups. |
| **Environment agnostic** | No `if env == "prod"` in pipeline code. Config is injected; pipelines are pure functions of config. |
| **Code-as-mode hygiene** | Every resource is declared in code. No manual GCP console actions. DAGs, pipelines, and feature schemas are version-controlled. |
| **DRY + Convention > Config** | A pipeline that follows conventions needs zero boilerplate config. Overrides are opt-in. |

---

## 2. Naming Convention System

### 2.1 Canonical Namespace Token

```
{team}-{project}-{branch}
```

- `team`: lowercase alphanumeric + hyphen, max 12 chars (e.g., `dsci`, `mleng`)
- `project`: lowercase alphanumeric + hyphen, max 20 chars (e.g., `churn-pred`, `reco-v2`)
- `branch`: git branch name, sanitized (slashes → double-dash, special chars stripped), max 30 chars

**Examples:**

| Git branch | Namespace token |
|---|---|
| `feature/user-embeddings` | `dsci-churn-pred-feature--user-embeddings` |
| `main` | `dsci-churn-pred-main` |
| `hotfix/v1.2.1` | `dsci-churn-pred-hotfix--v1.2.1` |

### 2.2 Resource Naming Map

| GCP Resource | Pattern |
|---|---|
| GCS bucket | `{namespace}` (one bucket per project, branches = prefixes) |
| GCS path prefix | `gs://{team}-{project}/{branch}/` |
| BigQuery dataset | `{team}_{project}_{branch_safe}` (underscored, BQ constraint) |
| BigQuery table | `{entity}_{feature_group}` within dataset |
| Vertex AI Experiment | `{namespace}` |
| Vertex AI Pipeline run | `{namespace}-{pipeline_name}-{timestamp}` |
| Vertex AI Endpoint | `{namespace}-{model_name}` |
| Cloud Composer DAG ID | `{namespace}--{dag_name}` |
| Feature Store Entity Type | `{entity}` within a Feature Store named `{team}-{project}` |
| Feature Store Feature View | `{entity}_{branch_safe}` |
| Artifact Registry repo | `{team}-{project}` (shared; images tagged `{branch_safe}-{sha}`) |

### 2.3 Branch Sanitization Rules

```python
import re

def sanitize_branch(branch: str) -> str:
    """Converts git branch to GCP-safe token."""
    return re.sub(r"[^a-z0-9\-]", "-", branch.lower()).strip("-")[:30]

def bq_safe(branch: str) -> str:
    """Converts git branch to BigQuery dataset-safe string."""
    return re.sub(r"[^a-z0-9_]", "_", branch.lower()).strip("_")[:30]
```

---

## 3. Directory Structure

```
{project-name}/                        # repo root
├── pyproject.toml                     # UV-managed, framework as dep
├── uv.lock
├── .python-version
├── framework.yaml                     # project-level convention config
│
├── pipelines/                         # user-defined pipelines (the core DSL)
│   ├── churn_prediction/
│   │   ├── pipeline.py                # pipeline composition (the only file you must edit)
│   │   └── config.yaml                # pipeline-level overrides (optional)
│   └── recommender/
│       ├── pipeline.py
│       └── config.yaml
│
├── components/                        # reusable KFP v2 component definitions
│   ├── ingestion/
│   │   ├── bigquery_extract.py
│   │   ├── gcs_extract.py
│   │   └── api_extract.py
│   ├── transformation/
│   │   ├── spark_transform.py
│   │   ├── bq_transform.py
│   │   └── pandas_transform.py
│   ├── feature_store/
│   │   ├── write_features.py
│   │   └── read_features.py
│   └── ml/
│       ├── train.py
│       ├── evaluate.py
│       └── deploy.py
│
├── dags/                              # Cloud Composer DAG definitions
│   ├── _base.py                       # shared DAG factory
│   └── {pipeline_name}_dag.py         # one DAG per pipeline (auto-generated template)
│
├── feature_schemas/                   # entity-centric feature definitions
│   ├── user.yaml
│   ├── item.yaml
│   └── session.yaml
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── .github/
│   └── workflows/
│       ├── ci.yaml                    # lint, test, build on PR
│       └── deploy.yaml                # deploy on push to main
│
└── scripts/
    └── bootstrap.sh                   # one-time GCP project setup
```

### 3.1 Framework Package Structure (pip-installable)

```
gcp_ml_framework/                      # installable library
├── __init__.py
├── naming.py                          # namespace resolution
├── config.py                          # Pydantic config system
├── context.py                         # runtime context (project, branch, region)
├── pipeline/
│   ├── __init__.py
│   ├── builder.py                     # PipelineBuilder DSL
│   ├── runner.py                      # local + Vertex AI runner
│   └── registry.py                   # component registry
├── components/
│   ├── base.py                        # BaseComponent ABC
│   ├── ingestion.py
│   ├── transformation.py
│   ├── feature_store.py
│   └── ml.py
├── dag/
│   ├── factory.py                     # DAG factory for Composer
│   └── operators.py                  # custom Airflow operators
├── feature_store/
│   ├── schema.py                      # FeatureSchema + EntityDef
│   └── client.py                     # Feature Store read/write
├── cli/
│   ├── __init__.py
│   ├── main.py                        # `gml` CLI entrypoint
│   ├── cmd_init.py
│   ├── cmd_run.py
│   ├── cmd_deploy.py
│   └── cmd_promote.py
└── utils/
    ├── gcp.py
    └── logging.py
```

---

## 4. Configuration System

### 4.1 Layered Config (Pydantic v2)

Config is resolved in this order (later layers override earlier):

```
framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags
```

```python
# gcp_ml_framework/config.py
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

class GCPConfig(BaseModel):
    project_id: str
    region: str = "us-central1"
    composer_env: str | None = None
    artifact_registry: str | None = None

class FeatureStoreConfig(BaseModel):
    online_serving_fixed_node_count: int = 1
    bigtable_min_node_count: int = 1

class FrameworkConfig(BaseSettings):
    team: str
    project: str
    branch: str = Field(default_factory=_get_git_branch)
    gcp: GCPConfig
    feature_store: FeatureStoreConfig = FeatureStoreConfig()

    model_config = SettingsConfigDict(
        env_prefix="GML_",
        env_nested_delimiter="__",
        yaml_file=["framework.yaml", "pipeline/config.yaml"],
    )
```

### 4.2 `framework.yaml` Example

```yaml
team: dsci
project: churn-pred
gcp:
  project_id: my-gcp-project
  region: us-central1
  composer_env: ml-composer-env
  artifact_registry: us-central1-docker.pkg.dev/my-gcp-project/dsci-churn-pred
```

### 4.3 Runtime Context

```python
# gcp_ml_framework/context.py
@dataclass(frozen=True)
class MLContext:
    config: FrameworkConfig
    namespace: str          # {team}-{project}-{branch}
    gcs_prefix: str         # gs://{team}-{project}/{branch}/
    bq_dataset: str         # {team}_{project}_{branch_safe}
    experiment: str         # vertex ai experiment name
```

The `MLContext` is the single object passed into every component and DAG. No globals, no env var spaghetti.

---

## 5. Pipeline DSL

### 5.1 `PipelineBuilder` — The Core DSL

The key design goal: a data scientist only edits `pipeline.py` to change their pipeline. No DAG code, no KFP YAML, no operator wiring.

```python
# pipelines/churn_prediction/pipeline.py
from gcp_ml_framework.pipeline import PipelineBuilder
from gcp_ml_framework.components import (
    BigQueryExtract, BQTransform, WriteFeatures,
    TrainModel, EvaluateModel, DeployModel,
)

pipeline = (
    PipelineBuilder(name="churn-prediction")
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{bq_dataset}.raw_events` WHERE dt = '{run_date}'",
            output_table="raw_events_extract",
        )
    )
    .transform(
        BQTransform(
            sql_file="sql/churn_features.sql",
            output_table="churn_features",
        )
    )
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="churn_signals",
            entity_id_column="user_id",
        )
    )
    .train(
        TrainModel(
            trainer_image="churn-trainer:latest",
            machine_type="n1-standard-8",
            hyperparameters={"learning_rate": 0.01, "max_depth": 6},
        )
    )
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.75},         # pipeline halts if gate not met
        )
    )
    .deploy(
        DeployModel(
            endpoint_name="churn-v1",
            traffic_split={"new": 10, "current": 90},  # canary
        )
    )
    .build()
)
```

### 5.2 Step-Level Flexibility

Adding, removing, or reordering steps = editing one file:

```python
# Remove training/deployment — feature engineering only pipeline
pipeline = (
    PipelineBuilder(name="churn-features-only")
    .ingest(BigQueryExtract(...))
    .transform(BQTransform(...))
    .write_features(WriteFeatures(...))
    .build()
)

# Swap transformer
pipeline = (
    PipelineBuilder(name="churn-spark")
    .ingest(GCSExtract(...))
    .transform(SparkTransform(script="pyspark/churn_transform.py"))  # different transformer
    .write_features(WriteFeatures(...))
    .build()
)
```

### 5.3 `PipelineBuilder` generates both:
1. A **KFP v2 pipeline** (`@pipeline` decorated function) for Vertex AI
2. A **Cloud Composer DAG** (via `dag/factory.py`) for orchestration scheduling

---

## 6. Component Library

### 6.1 `BaseComponent` ABC

```python
# gcp_ml_framework/components/base.py
from abc import ABC, abstractmethod
from kfp.v2 import dsl

class BaseComponent(ABC):
    """All components implement this interface."""

    @abstractmethod
    def as_kfp_component(self) -> dsl.ContainerSpec:
        """Returns a KFP v2 ContainerSpec for Vertex AI Pipelines."""
        ...

    @abstractmethod
    def as_airflow_operator(self, context: MLContext, dag) -> "BaseOperator":
        """Returns an Airflow operator for Cloud Composer."""
        ...

    def local_run(self, context: MLContext) -> None:
        """Run component logic locally for testing. Override if needed."""
        raise NotImplementedError("Local run not implemented for this component")
```

### 6.2 Built-in Components

| Category | Component | Description |
|---|---|---|
| **Ingestion** | `BigQueryExtract` | SQL query → GCS/BQ staging |
| | `GCSExtract` | GCS file → staging |
| | `APIExtract` | REST/HTTP → GCS |
| **Transformation** | `BQTransform` | SQL file → BQ table |
| | `SparkTransform` | PySpark script via Dataproc |
| | `PandasTransform` | Python function (small data, local-friendly) |
| **Feature Store** | `WriteFeatures` | BQ table → Vertex AI Feature Store |
| | `ReadFeatures` | Feature Store → BQ/GCS for training |
| **ML** | `TrainModel` | Custom container training job |
| | `EvaluateModel` | Evaluation + metric gating |
| | `DeployModel` | Model → Vertex AI Endpoint |

---

## 7. Cloud Composer DAG System

### 7.1 DAG Factory

```python
# gcp_ml_framework/dag/factory.py
def make_dag(pipeline_def: PipelineDefinition, context: MLContext) -> DAG:
    """
    Converts a PipelineDefinition into an Airflow DAG.
    DAG ID = {namespace}--{pipeline_name}
    """
    dag_id = f"{context.namespace}--{pipeline_def.name}"
    with DAG(dag_id=dag_id, schedule=pipeline_def.schedule, ...) as dag:
        tasks = {}
        for step in pipeline_def.steps:
            operator = step.component.as_airflow_operator(context, dag)
            tasks[step.name] = operator

        # Wire dependencies from pipeline definition order
        for i in range(1, len(pipeline_def.steps)):
            tasks[pipeline_def.steps[i-1].name] >> tasks[pipeline_def.steps[i].name]

    return dag
```

### 7.2 DAG File (auto-generated, checked in)

```python
# dags/churn_prediction_dag.py
from gcp_ml_framework.dag.factory import make_dag
from gcp_ml_framework.context import MLContext
from pipelines.churn_prediction.pipeline import pipeline as pipeline_def

context = MLContext.from_env()   # reads GML_* env vars set in Composer
dag = make_dag(pipeline_def, context)
```

Composer env vars `GML_TEAM`, `GML_PROJECT`, `GML_GCP__PROJECT_ID`, etc. are set once at environment level — no code changes between branches.

---

## 8. Feature Store Integration

### 8.1 Entity-Centric Schema (YAML)

```yaml
# feature_schemas/user.yaml
entity: user
id_column: user_id
id_type: STRING
feature_groups:
  churn_signals:
    description: "Churn prediction features"
    features:
      - name: days_since_last_login
        type: INT64
      - name: total_purchases_30d
        type: FLOAT64
      - name: support_tickets_90d
        type: INT64
  engagement:
    description: "Engagement metrics"
    features:
      - name: session_count_7d
        type: INT64
      - name: avg_session_duration_s
        type: FLOAT64
```

### 8.2 Feature Store Client

```python
# gcp_ml_framework/feature_store/client.py
class FeatureStoreClient:
    def write_features(
        self,
        bq_source: str,           # fully qualified BQ table
        entity: str,              # "user", "item", etc.
        feature_group: str,
        entity_id_column: str,
        context: MLContext,
    ) -> None:
        """Writes BQ table to Feature Store under the branch namespace."""
        feature_view_id = f"{entity}_{context.config.branch_safe}"
        # upsert to Vertex AI Feature Store ...
```

Branch-based Feature Store isolation: each branch writes to its own feature view (`user_feature__user-embeddings`), so experimental feature definitions never contaminate production serving.

---

## 9. CLI Tooling (`gml`)

Implemented with **Typer**. Installed via `uv tool install`.

```bash
# Initialize a new project
gml init --team dsci --project churn-pred --gcp-project my-gcp-project

# Run a pipeline locally (uses PandasTransform/local_run stubs)
gml run churn-prediction --local

# Compile pipeline to KFP YAML + submit to Vertex AI Pipelines
gml run churn-prediction --vertex

# Deploy DAG to Cloud Composer (syncs dags/ to Composer GCS bucket)
gml deploy dags

# Deploy feature schemas to Feature Store
gml deploy features user item

# Promote branch resources to another branch (e.g., feature → main)
gml promote --from feature/user-embeddings --to main --resource model:churn-v1

# Show the namespace and resource map for current branch
gml context show
```

### 9.1 `gml init` Scaffolds

- `framework.yaml` with team/project/GCP project
- `pipelines/__init__.py`
- `feature_schemas/` with example entity YAML
- `dags/_base.py`
- `pyproject.toml` with UV and `gcp-ml-framework` as dependency
- `.python-version` pinned to 3.11
- `.github/workflows/ci.yaml` and `deploy.yaml`

---

## 10. Local Development Workflow

```
Developer workstation
│
├─ gml run {pipeline} --local
│   ├── Resolves context from framework.yaml + git branch
│   ├── Replaces GCS/BQ steps with local filesystem stubs
│   ├── Runs PandasTransform components in-process
│   └── Writes feature data to local SQLite (Feature Store stub)
│
├─ pytest tests/unit/
│   └── Components tested with mock context + fixture data
│
└─ gml run {pipeline} --vertex   (optional, pre-PR smoke test)
    └── Submits real Vertex AI Pipeline run under branch namespace
```

### 10.1 Local Stub Strategy

Each component has an optional `local_run(context)` method. The `LocalRunner` calls this instead of submitting to GCP. Data scientists get fast iteration loops without GCP costs.

```python
class BQTransform(BaseComponent):
    def local_run(self, context: MLContext) -> None:
        # Read from local parquet instead of BQ, apply SQL via duckdb
        import duckdb
        duckdb.sql(self.sql_template.format(**context.vars)).write_parquet(...)
```

---

## 11. GCP Deployment Workflow

```
Git push → GitHub Actions
│
├─ ci.yaml (every PR)
│   ├── uv sync
│   ├── ruff lint + mypy
│   ├── pytest tests/unit/
│   └── gml run {changed_pipelines} --compile-only  (KFP compile check)
│
└─ deploy.yaml (push to main)
    ├── gml deploy dags           → sync to Composer GCS bucket
    ├── gml deploy features       → upsert Feature Store schemas
    └── gml run {all} --vertex    → submit Vertex AI Pipeline runs
```

### 11.1 Environment Promotion

Environments = GCP projects + branch (`main`). Promotion is:

1. PR from `feature/X` → `main`
2. CI runs full test suite
3. On merge, deploy workflow triggers for `main` branch namespace
4. `gml promote --resource model:churn-v1` copies a validated model artifact from feature namespace → main namespace and updates the Endpoint traffic split

No separate "staging" environment config files. Staging IS the feature branch.

---

## 12. `pyproject.toml` & UV Configuration

```toml
[project]
name = "gcp-ml-framework"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "kfp>=2.7,<3",
    "google-cloud-aiplatform>=1.49",
    "google-cloud-bigquery>=3.17",
    "google-cloud-storage>=2.16",
    "apache-airflow>=2.8",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "typer>=0.12",
    "rich>=13",
    "pyyaml>=6",
    "duckdb>=0.10",           # local SQL execution
    "pyarrow>=15",
]

[project.scripts]
gml = "gcp_ml_framework.cli.main:app"

[tool.uv]
dev-dependencies = [
    "pytest>=8",
    "pytest-cov",
    "ruff",
    "mypy",
    "google-cloud-testutils",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
strict = true
```

---

## 13. Naming Standard Enforcement

A `ruff` plugin (or pre-commit hook) enforces:
- No hardcoded GCP project IDs, bucket names, or dataset names in `.py` files (must come from context)
- No `os.environ.get("ENV")` style environment checks
- `gml lint` command runs these checks + validates `feature_schemas/*.yaml` against schema

---

## 14. Implementation Phases

### Phase 1 — Foundation (Week 1–2)
- [ ] `gcp_ml_framework` package scaffold (UV project setup)
- [ ] `naming.py`: namespace resolution + sanitization
- [ ] `config.py`: Pydantic config with YAML + env var layering
- [ ] `context.py`: `MLContext` dataclass
- [ ] `gml init` CLI command + project scaffolding
- [ ] `gml context show` command

### Phase 2 — Component Library (Week 2–3)
- [ ] `BaseComponent` ABC
- [ ] `BigQueryExtract` + local DuckDB stub
- [ ] `BQTransform` + local DuckDB stub
- [ ] `WriteFeatures` + local SQLite stub
- [ ] `ReadFeatures`
- [ ] `TrainModel` (custom container)
- [ ] `EvaluateModel` with metric gating
- [ ] `DeployModel`
- [ ] Unit tests for all components with mock context

### Phase 3 — Pipeline DSL & DAG Factory (Week 3–4)
- [ ] `PipelineBuilder` DSL
- [ ] KFP v2 pipeline compilation from `PipelineBuilder`
- [ ] Cloud Composer DAG factory
- [ ] `gml run --local` (LocalRunner)
- [ ] `gml run --vertex` (VertexRunner)
- [ ] `gml run --compile-only` (for CI)

### Phase 4 — Feature Store Integration (Week 4–5)
- [ ] Feature schema YAML parser + validator
- [ ] `FeatureStoreClient` (write/read)
- [ ] `gml deploy features` command
- [ ] Branch-namespaced feature views
- [ ] Integration tests against Vertex AI Feature Store

### Phase 5 — CLI & Developer Experience (Week 5–6)
- [ ] `gml deploy dags` (Composer DAG sync)
- [ ] `gml promote` (artifact promotion between namespaces)
- [ ] `gml lint` (naming convention enforcement)
- [ ] `gml context show` (full resource map)
- [ ] Project template (cookiecutter or `gml init`)

### Phase 6 — CI/CD & Documentation (Week 6–7)
- [ ] GitHub Actions: `ci.yaml` + `deploy.yaml` templates
- [ ] `bootstrap.sh` for one-time GCP project setup (IAM, APIs, Composer env)
- [ ] End-to-end example pipeline (churn prediction)
- [ ] Developer guide
- [ ] Naming convention reference

---

## 15. Key Design Decisions & Rationale

| Decision | Rationale |
|---|---|
| KFP v2 + Airflow (not one or the other) | KFP handles ML-specific concerns (artifacts, lineage, GPU scheduling); Airflow handles data engineering scheduling and dependency management across pipelines. |
| Branch = resource namespace (not env var) | Eliminates "works on my branch" bugs. Isolation is structural, not reliant on human discipline. |
| Pydantic config (not dataclasses/dicts) | Validation at load time, IDE autocomplete, clear error messages for misconfiguration. |
| DuckDB for local stubs | SQL-compatible with BigQuery, zero infrastructure, runs in-process. Data scientists can validate SQL logic locally. |
| Feature schemas in YAML, not Python | Non-engineers can read/edit them. YAML is version-controlled and diff-friendly. Python-based validation enforces schema correctness. |
| `gml` CLI over Makefiles | Makefile targets don't carry type safety, help text, or argument validation. Typer CLI is self-documenting and testable. |
| No `if env == "prod"` anywhere | Forces clean separation. All environment differences live in config injection at the boundary (CI/CD, Composer env vars). |

---

## 16. Open Questions for Review

1. **Feature Store version**: Vertex AI Feature Store (Bigtable-backed online serving) vs. Feature Store Legacy? Online serving required?
2. **Spark/Dataproc**: Is `SparkTransform` needed in Phase 1, or can teams start with BQ SQL transforms only?
3. **Model serving**: Vertex AI Endpoint only, or also need Batch Prediction support?
4. **Multi-region**: Single region (`us-central1`) to start, or multi-region from day one?
5. **Secrets management**: GCP Secret Manager integration needed in Phase 1, or assume service account key-less auth (Workload Identity)?
6. **DAG scheduling**: Should `PipelineBuilder` accept a `schedule` parameter, or is scheduling always defined at the DAG level separately?
