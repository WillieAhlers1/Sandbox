# GCP ML Framework (`gcp_ml_framework`)

A pip-installable ML platform framework where data scientists define pipelines with Python decorators (`@task`, `@ml_task`), write business logic in `run()` methods, and the framework handles compilation to KFP YAML, Airflow DAG generation, Docker image management, and deployment to Vertex AI via Cloud Composer.

## How It Works

```mermaid
flowchart LR
    subgraph DS ["Data Scientist"]
        A["pipeline.py\n+ steps/"]
    end

    subgraph CLI ["GML CLI"]
        B["gml compile"]
        C["gml build"]
        D["gml deploy"]
        E["gml run"]
    end

    subgraph GCP ["Google Cloud"]
        F["Artifact Registry\n(Docker images)"]
        G["Cloud Composer\n(Airflow DAGs)"]
        H["Vertex AI\n(ML Pipelines)"]
        I["Vertex AI\n(Endpoints)"]
    end

    A -->|define| B
    B -->|"KFP YAML\n+ Airflow DAG"| C
    C -->|"Cloud Build"| F
    D -->|"upload DAGs\n+ YAML"| G
    E -->|"trigger DAG"| G
    G -->|"submit pipeline"| H
    H -->|"deploy model"| I

    style DS fill:#e8f5e9,stroke:#2e7d32
    style CLI fill:#e3f2fd,stroke:#1565c0
    style GCP fill:#fff3e0,stroke:#e65100
```

Data scientists write pipeline definitions using the builder API:

```python
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.deploy import DeployModel
from my_project.steps.train_model import MyTrainStep

pipeline = (
    Pipeline(name="my_pipeline", schedule="@daily")
    .add(MyTrainStep(
        component_name="train",
        runtime_dockerfile="pipelines/my_pipeline/base.Dockerfile",
    ), name="Train Model")
    .add(RegisterModel(
        model_name="my-model",
        runtime_dockerfile="pipelines/my_pipeline/base.Dockerfile",
        serving_dockerfile="pipelines/my_pipeline/serve.Dockerfile",
    ), name="Register Model")
    .add(DeployModel(
        model_name="my-model",
        runtime_dockerfile="pipelines/my_pipeline/base.Dockerfile",
    ), name="Deploy Model")
    .build()
)
```

## Pipeline Lifecycle

```mermaid
flowchart TD
    subgraph DEFINE ["1. Define"]
        P["Pipeline builder\n.add() .for_each() .condition()"]
    end

    subgraph COMPILE ["2. Compile"]
        SC["SmartCompiler"]
        SC --> YAML["KFP YAML\n(Vertex AI steps)"]
        SC --> DAG["Airflow DAG\n(orchestration)"]
    end

    subgraph BUILD ["3. Build"]
        BP["base-python"]
        BP --> PB["{pipeline}--base\n(framework + deps)"]
        PB --> PS["{pipeline}--serve\n(FastAPI + model)"]
    end

    subgraph DEPLOY ["4. Deploy"]
        GCS["YAML → GCS"]
        COMP["DAG → Composer"]
        IMG["Images → verified"]
    end

    subgraph RUN ["5. Run"]
        AF["Airflow triggers DAG"]
        AF --> VTX["Vertex AI runs\nML pipeline"]
        VTX --> EP["Model deployed\nto endpoint"]
    end

    P --> SC
    YAML --> GCS
    DAG --> COMP
    GCS --> AF
    COMP --> AF

    style DEFINE fill:#e8f5e9,stroke:#2e7d32
    style COMPILE fill:#e3f2fd,stroke:#1565c0
    style BUILD fill:#f3e5f5,stroke:#6a1b9a
    style DEPLOY fill:#fff3e0,stroke:#e65100
    style RUN fill:#fce4ec,stroke:#b71c1c
```

## Component Model

```mermaid
flowchart LR
    subgraph TASK ["@task — Airflow Operators"]
        BQ["BQQuery"]
        BT["BQTransform"]
        DBT["DBTRun"]
        EM["Email"]
    end

    subgraph ML ["@ml_task — Vertex AI Containers"]
        TM["TrainModel"]
        EV["EvaluateModel"]
        RM["RegisterModel"]
        DM["DeployModel"]
    end

    subgraph LIFECYCLE ["Lifecycle"]
        direction TB
        CLI["cli()"] --> EXE["execute()"]
        EXE --> RUN["run()"]
    end

    TASK -.->|"render_operator()\n→ Airflow code"| DAG2["Airflow DAG"]
    ML -.->|"as_kfp_component()\n→ container spec"| KFP["KFP YAML"]

    style TASK fill:#e3f2fd,stroke:#1565c0
    style ML fill:#f3e5f5,stroke:#6a1b9a
    style LIFECYCLE fill:#e8f5e9,stroke:#2e7d32
```

## Quick Start

```bash
# Install
git clone <repo-url> && cd <repo>
uv sync

# Configure
cp .env.example .env
# Edit .env with your GCP project, team, service accounts

# Compile → Build → Deploy → Run
UV_ENV_FILE=.env uv run -- gml compile --all
UV_ENV_FILE=.env uv run -- gml build house_price
UV_ENV_FILE=.env uv run -- gml deploy --all
UV_ENV_FILE=.env uv run -- gml run house_price
```

See [docs/guides/quickstart.md](docs/guides/quickstart.md) for the full walkthrough.

## CLI

| Command | Description |
|---------|-------------|
| `gml compile [name \| --all]` | Compile pipeline(s) to KFP YAML + Airflow DAG |
| `gml build [name \| --all]` | Build Docker images via Cloud Build |
| `gml deploy [name \| --all]` | Deploy DAGs + YAMLs + verify images |
| `gml run [name] [--local]` | Trigger via Composer, or `--local` for in-process |
| `gml context show` | Show resolved config and resource names |
| `gml teardown [--branch]` | Delete ephemeral dev resources |

## Project Structure

```
gcp_ml_framework/          Framework library
├── cli/                     CLI commands (compile, build, deploy, run)
├── components/              BaseComponent + ML/operator/transformation components
├── pipeline/                Builder, SmartCompiler, PipelineCompiler, LocalRunner
├── config.py                FrameworkConfig + GCPConfig (pydantic-settings)
├── context.py               MLContext (immutable runtime context)
├── naming.py                NamingConvention (all GCP resource names)
└── decorators.py            @task and @ml_task decorators

pipelines/                 Pipeline definitions
├── house_price/             Reference implementation (train → register → deploy)
├── training_pipeline/       Full lifecycle (ingest → transform → train → eval → register → deploy)
└── verification_pipeline/   Exercises ALL capabilities (loops, conditions, monitoring)

app/                       Per-pipeline FastAPI serving apps
docker/                    Dockerfiles (base-python → pipeline--base → pipeline--serve)
second_run/                Shared business logic (estimators, feature engineering)
tests/                     Unit / integration / e2e test suite
```

## Branch Isolation

Every branch gets its own isolated GCP resources — no cross-contamination between developers.

```mermaid
flowchart TD
    subgraph SHARED ["Shared (all branches)"]
        BUCKET["GCS Bucket\nprj-sandbox-mlplatform-second-run"]
        AR["AR Repo\nmlplatform-second-run"]
    end

    subgraph BRANCH_A ["Branch: feature-xyz"]
        BQ_A["BQ Dataset\nmlplatform_second_run_feature_xyz"]
        GCS_A["GCS Prefix\n/feature-xyz/"]
        DAG_A["DAG\n...feature_xyz__pipeline"]
        VTX_A["Vertex AI\n...feature-xyz-..."]
    end

    subgraph BRANCH_B ["Branch: main"]
        BQ_B["BQ Dataset\nmlplatform_second_run_main"]
        GCS_B["GCS Prefix\n/main/"]
        DAG_B["DAG\n...main__pipeline"]
        VTX_B["Vertex AI\n...main-..."]
    end

    BUCKET --> GCS_A
    BUCKET --> GCS_B
    AR --> BRANCH_A
    AR --> BRANCH_B

    style SHARED fill:#fff3e0,stroke:#e65100
    style BRANCH_A fill:#e3f2fd,stroke:#1565c0
    style BRANCH_B fill:#e8f5e9,stroke:#2e7d32
```

## Configuration

All config via `.env` (gitignored). Key variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `TEAM` | Team identifier | `mlplatform` |
| `PROJECT` | Project name | `second_run` |
| `ENVIRONMENT` | Runtime environment | `dev` |
| `GCP_PROJECT_ID` | GCP project | `prj-my-sandbox` |
| `GCP_REGION` | GCP region | `us-east4` |

All GCP resource names are derived from `{team}-{project}-{branch}` via `NamingConvention`. See [docs/operations/configuration.md](docs/operations/configuration.md).

## Development

```bash
# Unit tests (fast, no GCP)
uv run -- pytest tests/ -m unit -v

# Lint + type check
uv run -- ruff check gcp_ml_framework tests
uv run -- mypy gcp_ml_framework/
```

| Tier | Scope | GCP Required | Speed |
|------|-------|-------------|-------|
| Unit | Framework logic, mocked | No | <30s |
| Integration | Real BQ/GCS on dev | Yes | Minutes |
| E2E | Full pipeline on Vertex AI | Yes | 5-10 min |

## Documentation

| Section | What you'll find |
|---------|-----------------|
| [Architecture](docs/architecture/) | System design, component model, compilation, ADRs |
| [Guides](docs/guides/) | Quickstart, writing components, writing pipelines, deployment |
| [Operations](docs/operations/) | Cloud Build, configuration, GCP resources, platform guide, testing |
| [Reference](docs/reference/) | Requirements status |

## Stack

- **Language:** Python 3.12
- **Package manager:** uv (exclusively)
- **Orchestration:** KFP v2 on Vertex AI, triggered by Airflow (Cloud Composer)
- **Docker:** Per-pipeline images built via Google Cloud Build
- **Serving:** Per-pipeline FastAPI apps on Vertex AI endpoints
- **Testing:** pytest with three-tier strategy (unit/integration/e2e)
- **Logging:** loguru
