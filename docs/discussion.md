# Project Discussion Log: version_1 Architecture & Roadmap

**Date:** 2026-03-20
**Participants:** Engineering Lead + AI Assistant
**Project:** GCP ML Framework (`gcp_ml_framework`) — `version_1` branch

---

## 1. Project Background

### What We're Building
A pip-installable ML platform framework where data scientists define pipelines with simple Python decorators (`@task`, `@ml_task`), write business logic in `run()` methods, and the framework handles compilation to KFP YAML, Airflow DAG generation, Docker image management, and deployment to Vertex AI.

### Starting Point
- **`test` branch:** Mature, feature-complete (3 pipelines, 451 tests, DuckDB local execution). Old architecture: `@dsl.component` with inlined Python, per-component KFP boilerplate, nested CustomJob for training.
- **`version_1` branch:** Ground-up redesign of component system. Better architecture (`@dsl.container_component`, `BaseComponent` lifecycle, step subclass pattern) but only 1 pipeline, 0 tests, broken imports.

### Repository
- Repo: `git@github.com:<org>/<repo>.git` (branch: `version_1`)

---

## 2. Architecture Decisions

### Decision 1: Unified Task Architecture

**Problem:** Data scientists face cognitive overload with two parallel systems — PipelineBuilder + BaseComponent (for Vertex AI) and DAGBuilder + BaseTask (for Airflow). They must decide "is this a DAG or Pipeline?" and learn different base classes, builders, and execution models.

**Decision:** Unify into a single system with `@task` and `@ml_task` decorators.

- `@task` = lightweight work (BQ queries, emails, notifications). Compiled to Airflow operators.
- `@ml_task` = heavy ML compute (training, evaluation, deployment). Compiled to Vertex AI container components.
- Single `Pipeline` builder replaces both `PipelineBuilder` and `DAGBuilder`.
- The "smart compiler" auto-groups consecutive `@ml_task` steps into a Vertex AI pipeline and wraps everything in an Airflow DAG.

**Rationale:**
- Aligned with industry direction (Metaflow, Flyte, ZenML use unified task abstractions)
- Eliminates `BigQueryExtract` vs `BQQueryTask` confusion
- Data scientists learn one system, not two
- The framework makes infrastructure decisions, not data scientists

**Impact:** Major refactor touching ~20 files, ~1500-2000 lines changed. Justified because codebase is small (~3700 lines) and only 1 pipeline exists.

**Alternative considered (rejected):** Light touch — just rename PipelineBuilder to Pipeline, document that data scientists never touch DAGBuilder. Gets 80% of value with 20% effort. Rejected because: "We do things the right way."

---

### Decision 2: Environment Resolution Owned by CI/CD, Not Framework

**Problem (REQS 16.0):** Framework reads git branch name to determine environment (DEV/STAGING/PROD). This couples framework to git conventions.

**Decision:** Remove `_resolve_git_state()` from framework. Environment is a direct input via `GML_ENVIRONMENT` env var, set by CI/CD or `.env`.

**Rationale:**
- Industry standard: framework answers "what", deployment system answers "where"
- In containers, there's no `.git` directory — branch-based resolution never ran inside Vertex AI anyway
- Multi-team usage: teams may use different branch naming conventions
- Testability: test staging behavior by setting env var, not faking git branch

**What stays:** `get_git_branch()` remains for **resource naming only** (branch isolation in BQ datasets, GCS paths). It does NOT determine environment.

**Environment enum values:** LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT
- TEST = QA environment (confirmed by user)
- EXPERIMENT = production A/B tests (replaces PROD_EXP)

---

### Decision 3: Local Testing Strategy

**Problem:** How do data scientists validate pipelines locally?

**Decision:** Three-tier approach:

| Tier | What | Hits GCP? | Speed |
|---|---|---|---|
| Unit tests | Framework logic, component instantiation, compiler output | No (mocked) | <30 seconds |
| Integration tests | Individual step `execute()` against real BQ/GCS | Yes (dev project) | Minutes |
| E2E tests | Full pipeline on Vertex AI | Yes (dev project) | 5-10 minutes |

**For data scientist iteration:** `gml run --local` always hits real GCP dev resources. No DuckDB, no mocks.

**Rationale:**
- DuckDB SQL translation can diverge from BigQuery semantics
- Real dev project exists — use it
- `execute()` code is identical locally and on Vertex AI
- Unit tests stay fast and hermetic (no GCP needed for framework development)

---

### Decision 4: DBT Integration (Not Deferred)

**Problem (REQS 19.0):** Verify Composer can trigger DBT jobs.

**Decision:** Build first-class DBT support — not just verification.

**What DBT does:**
- Transforms raw data into feature tables via SQL models with dependency resolution
- Handles incremental loads, testing, documentation
- Replaces manual SQL files in `pipelines/*/sql/` for transformation steps
- Complements (not replaces) Vertex AI Feature Store

**DBT + Feature Store relationship:**
```
Raw Data → DBT (compute features) → BQ tables → Feature Store (serve features online)
```

**Changes needed:**
- New `DbtRunTask` component (compiles to Airflow `BashOperator` or `CloudBuildRunBuildOperator`)
- `profiles.yml` auto-generation from `.env`
- Composer needs `dbt-bigquery` PyPI package
- Reference `dbt/` project scaffold in training_pipeline
- `gml init pipeline --dbt` scaffold support

---

### Decision 5: Experiment Tracking Built Into Lifecycle

**Decision:** Auto-log hyperparameters and metrics to Vertex AI Experiments inside `TrainModel.execute()` and `EvaluateModel.execute()`.

**Rationale:** Table stakes for ML platforms. Data scientists get experiment tracking for free. The `experiment_name` field already exists but is unused.

---

### Decision 6: External Package Support

**Problem:** `second_run` is a business logic package (estimators, feature engineering) that multiple data scientists and pipelines share. Can they use it in the unified system?

**Decision:** Yes — this works naturally with the container component pattern.

**How it works:**
1. `second_run` is listed as a dependency in `pyproject.toml`
2. Docker images install it automatically
3. `@ml_task` step's `run()` method imports from it: `from second_run.estimator import HousePredictionModel`
4. Multiple pipelines share the same package
5. Different branches can pin different versions

**Scales to multiple teams:**
- Team A: `fraud-detection` package
- Team B: `recommendation-models` package
- Both use `gcp-ml-framework` for infrastructure

---

### Decision 7: Cloud Build for All Builds (Local + CI/CD)

**Problem (REQS 18.0):** Local `docker buildx` on developer machines is slow, requires Docker Desktop (licensing issues), build cache is local (not shared between developers), and CI runners have limited resources.

**Decision:** Google Cloud Build as the one and only build method. New `gml build` CLI command wraps `gcloud builds submit`. Works from developer laptops, CI runners, anywhere with `gcloud`.

**Rationale:**
- Data scientists don't need Docker Desktop installed (just `gcloud` CLI, already required)
- Shared AR layer cache: first build installs pip deps (~5 min), subsequent builds ~30-60s for everyone
- Cloud Build machines (up to 32 vCPU) are faster than laptops/CI runners
- Same command everywhere — "it built on my machine" eliminated
- Cost is not a concern for this project

**Changes:**
- New `gml build [pipeline | --all]` CLI command
- New `cloudbuild.yaml` with multi-step build + `--cache-from` AR caching
- New `.gcloudignore` to exclude secrets from build context
- Docker hierarchy simplified: `base-python` → `{pipeline-name}` (2 layers)
- Terraform: Cloud Build SA needs AR writer + storage admin roles
- `docker buildx` kept as undocumented escape hatch

---

### Decision 8: Test Organization

**Decision:** Tests grouped by functionality, not flat by file type.

```
tests/
├── config/              (config, context, naming, environment)
├── components/          (base, train, evaluate, register, deploy, etc.)
├── pipeline/            (builder, compiler, local_runner)
├── dag/                 (builder, compiler, factory)
├── cli/                 (all CLI commands)
├── training_pipeline/   (step tests, integration, e2e)
└── conftest.py
```

Markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`

---

### Decision 9: Docker Image Hierarchy Simplification

**Problem (REQS 18.0b):** Current hierarchy has 3 base images: `base-python`, `component-base`, `base-ml`. With the unified architecture, there's no separate "component" vs "trainer" concept.

**Decision:** Simplify to 2 layers:
```
base-python:tag            (Python 3.12 + uv — cached, changes rarely)
  └── {pipeline-name}:tag  (base-python + all deps + source code — per pipeline)
```

`component-base` and `base-ml` merge into a single pipeline image that installs all extras.

**Rationale:** Unified architecture means every container runs the same code. Fewer images to build, cache, and manage.

---

### Decision 10: Cost Labels on GCP Resources

**Problem:** No visibility into per-pipeline, per-branch, per-team costs.

**Decision:** Apply standard labels to every GCP resource the framework creates:
```python
labels = {
    "team": naming.team,
    "project": naming.project,
    "branch": naming.branch_slug,
    "pipeline": pipeline_name,
    "managed_by": "gcp-ml-framework",
}
```

Applied to: Vertex AI pipeline runs, BQ jobs, GCS objects (metadata), Cloud Build submissions, Terraform resources.

**Rationale:** Zero effort for data scientists. Enables cost allocation via GCP billing export.

---

## 3. REQS.docx Decisions (All 23 Items)

### P0 Requirements

| ID | Requirement | Decision |
|---|---|---|
| 1.0 | Unified Component Lifecycle | **DONE** on version_1. Container components, BaseComponent lifecycle. |
| 5.0 | Airflow DAG 403 Permission | **DONE**. Terraform IAM bindings. |
| 6.0 | YAML Embeds Python Source | **DONE** (by 1.0). Container components emit ContainerSpec, not inlined Python. |
| 7.0 | Pydantic Migration | **DONE**. All dataclasses → Pydantic BaseModel. |
| 8.0 | Replace Argparse with Typer | **DONE**. BaseComponent.cli() uses Typer. gml CLI uses Typer. |
| 11.0 | Simplify PipelineBuilder API | **Phase included.** Collapse to `.add()` with stage inference from component type. Named methods kept as optional aliases. |
| 12.0 | Refactor CLI Entrypoints | **DONE** (by 1.0). `python -m step_module --help` works. |
| 13.0 | Flatten ComponentConfig | **Phase 1.** Move machine_type, accelerator, etc. directly onto BaseComponent. Remove ComponentConfig class. |
| 14.0 | Expose Standard Variables | **Phase included.** GML_PROJECT, GML_REGION, GML_ENVIRONMENT etc. as env vars in containers. |
| 15.0 | Rename GitState to Environment | **Phase 1.** New enum: LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT. Environment set via GML_ENVIRONMENT env var, not derived from git. |
| 21.0 | Model Registry Step | **Phase 1.** Create RegisterModel component. Compiler already has wiring for it. |
| 22.0 | Conditional/Loop Operators | **Phase included.** `.for_each()` → dsl.ParallelFor. `.condition()` → dsl.Condition. |

### P1 Requirements

| ID | Requirement | Decision |
|---|---|---|
| 2.0 | Underscore Normalization | **DONE**. Terraform `local.project_slug`. |
| 3.0 | Cleanout Invalid DAGs | **Phase included.** Verify `gml teardown` handles this. Add stale DAG detection. |
| 4.0 | Docker Build Tag Issue | **DONE**. Tags are `{branch}-{short_sha}`. |
| 9.0 | Structured Logging | **Phase included.** Replace remaining print() with loguru. JSON serialization for Cloud Logging. |
| 16.0 | Separate CI/CD from Framework | **Addressed by Decision 2.** Environment resolution moved to CI/CD. Branch kept only for resource naming. |
| 18.0 | Docker Cloud Build | **Phase included (un-deferred).** Cloud Build for ALL builds (local + CI/CD). New `gml build` command. See Decision 7. |
| 18.0b | Simplify Docker Hierarchy | **Phase included (un-deferred).** Merge component-base and base-ml into single pipeline image. 2-layer hierarchy. |

### P2 Requirements

| ID | Requirement | Decision |
|---|---|---|
| 10.0 | Google-Style Docstrings | **Phase included.** Priority: public API classes/methods data scientists use. |
| 17.0 | Enforce Mypy Annotations | **Phase included.** Start with `--warn-return-any`, strict mode later. |
| 19.0 | DBT Integration | **NOT deferred.** Full DBT support: DbtRunTask, profiles.yml generation, reference project. See Decision 4. |
| 20.0 | AGENTS.md | **Phase included.** AI coding guidelines for framework. |

---

## 4. Key Technical Details

### The Smart Compiler (Unified Architecture)

Input: Pipeline with mixed `@task` and `@ml_task` steps.

```
@task IngestHousing          ─┐
@task TransformFeatures       │ → Airflow operators
@ml_task TrainModel          ─┐
@ml_task EvaluateModel        │ → Grouped into ONE Vertex AI pipeline
@ml_task RegisterModel       ─┘
@task NotifyTeam             ─── → Airflow operator
```

Output:
1. **Airflow DAG** with: BQ operator → BQ operator → RunPipelineJobOperator → Email operator
2. **KFP YAML** with: Train → Evaluate → Register (the Vertex AI pipeline)

Edge case: `@ml_task, @task, @ml_task` = two separate Vertex AI pipelines with an Airflow task between them. The compiler handles this by detecting group boundaries.

### Cross-System Data Flow

- **Between @task steps:** Airflow XCom or BQ table references (lightweight)
- **Between @ml_task steps:** KFP output artifacts (GCS URIs)
- **From @task to @ml_task:** The Airflow DAG passes the BQ table reference as a parameter to the Vertex AI pipeline
- **From @ml_task to @task:** Vertex AI pipeline output (GCS URI) available as Airflow XCom after RunPipelineJobOperator completes

### Local Execution (`gml run --local`)

Runs ALL steps in-process regardless of decorator:
1. `@task` steps: calls `execute()` directly (real BQ query, real GCS)
2. `@ml_task` steps: calls `execute()` directly (same code as Vertex AI container)
3. No Docker, no Airflow, no Vertex AI overhead
4. Same code paths, same GCP resources, zero divergence

---

## 5. What's NOT Changing

| Area | Why |
|---|---|
| Container component pattern | Core to version_1's value. Every step is `python -m step_module --flags`. |
| NamingConvention | Single source of truth for all resource names. Branch-namespaced. |
| Pydantic models | Already migrated. All configs, components, definitions are Pydantic. |
| Terraform structure | Infrastructure as code. Per-environment configs. |
| CLI (`gml`) | Stays as the primary interface. Commands may be updated but pattern stays. |
| pyproject.toml structure | Optional deps groups (components, trainer, dev). Entry point: `gml`. |
| Docker image pattern | Base-python → pipeline-specific image. Git-derived tags. |

---

## 6. Open Items (Resolved)

| Question | Resolution |
|---|---|
| What does "Test" environment mean? | QA environment. Keep it. Gets its own resource namespace. |
| Remove all git logic from framework? | Yes. Environment comes from `GML_ENVIRONMENT` env var. Branch stays for resource naming only. |
| Local testing approach? | Three-tier: unit (mocked), integration (real GCP), e2e (real GCP). `gml run --local` always real. |
| Defer DBT? | No. Build first-class support. |
| Experiment tracking? | Yes. Built into TrainModel/EvaluateModel lifecycle. |
| Full unified refactor or light touch? | Full refactor. "We do things the right way." |

---

## 7. Deferred Items

| Item | Why Deferred |
|---|---|
| PyPI publishing | No external consumers yet. Package stays in monorepo. |
| Cookiecutter/template repo | Need stable API first. |
| Multi-environment promotion | CI/CD concern, not framework concern. |
| Custom UIs | Vertex AI Experiments UI and Airflow UI are sufficient. |

---

## 8. Data Scientist & Platform Team Journey

### The Big Picture

```
┌──────────────────────────────────────────────────────────┐
│                    DATA SCIENTIST                         │
│                                                          │
│   1. Write model code        →  second_run/estimator.py  │
│   2. Define pipeline         →  pipelines/*/pipeline.py  │
│   3. Test locally            →  gml run --local          │
│   4. Push branch             →  CI/CD handles the rest   │
│                                                          │
│   They never touch: KFP, Airflow, Docker, Terraform,     │
│                     IAM, GCS, Artifact Registry          │
└──────────────────────────────────────────────────────────┘
                           │
                    uses as dependency
                           │
┌──────────────────────────────────────────────────────────┐
│                    PLATFORM TEAM                          │
│                                                          │
│   Maintains: gcp_ml_framework package                    │
│   Manages:   Terraform, Composer, Docker base images     │
│   Sets up:   CI/CD, IAM, monitoring                      │
│   Publishes: gcp-ml-framework to internal PyPI           │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Data Scientist Day-to-Day

**Day 0 — Project Setup:**
```bash
git clone git@github.com:team/my-ml-project.git && cd my-ml-project
uv sync
cp .env.example .env  # Fill in with values from platform team
```

**Day 1 — Write a Pipeline:**
```python
# pipelines/training_pipeline/pipeline.py
from gcp_ml_framework import Pipeline, task, ml_task
from gcp_ml_framework.components import BQQuery, BQTransform, TrainModel, EvaluateModel, RegisterModel
from second_run.estimator import HousePredictionModel

@ml_task(machine_type="n2-standard-4")
class TrainHouseModel(TrainModel):
    def run(self):
        data = self.read_bq(self.dataset_uri)
        model = HousePredictionModel()
        model.fit(data.drop(columns=["price"]), data["price"])
        self.save_model(model)

pipeline = (
    Pipeline(name="training_pipeline", schedule="@daily")
    .add(BQQuery(sql="SELECT * FROM `{bq_dataset}.housing_data`"), name="Ingest")
    .add(BQTransform(sql_file="sql/features.sql"), name="Transform")
    .add(TrainHouseModel(), name="Train")
    .add(EvaluateModel(metrics=["rmse", "mae"], gate={"rmse": 50000}), name="Evaluate")
    .add(RegisterModel(), name="Register")
    .build()
)
```

**Day 2 — Test Locally:**
```bash
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local
```

**Day 3 — Deploy:**
```bash
git push origin feature/better-model  # CI/CD handles compilation, build, deployment
```

**Branch isolation:** Every branch gets its own namespace (BQ dataset, GCS path, DAG, Vertex AI pipeline). No collision between data scientists.

### What the Framework Does Behind the Scenes

```
Input: pipeline.py with mixed @task and @ml_task steps

Step 1: Parse pipeline definition
  → [BQQuery(@task), BQTransform(@task), TrainModel(@ml_task),
     EvaluateModel(@ml_task), RegisterModel(@ml_task)]

Step 2: Group by execution target
  → Airflow group: [BQQuery, BQTransform]
  → Vertex AI group: [TrainModel, EvaluateModel, RegisterModel]

Step 3: Compile Vertex AI group → KFP YAML
Step 4: Generate Airflow DAG with BQ operators + RunPipelineJobOperator

Output: One DAG file + one YAML file
```

### Platform Team Responsibilities

| Task | Frequency |
|---|---|
| Maintain `gcp_ml_framework` package | As needed |
| Manage Docker base images | On framework update |
| Terraform updates (IAM, storage, Composer) | Per env change |
| Cost monitoring (by team/project/branch labels) | Weekly |
| Stale branch cleanup (`gml teardown`) | Automated daily |

### What Each Role Touches

| | Data Scientist | Platform Team |
|---|---|---|
| **Writes** | `pipeline.py`, `estimator.py`, SQL files | `gcp_ml_framework/`, Terraform, CI/CD |
| **Commands** | `gml run --local`, `gml compile`, `pytest` | `gml deploy`, `terraform apply`, `gml build` |
| **Knows about** | Components, `@task`/`@ml_task`, `.add()`, `run()` | KFP, Airflow, Docker, IAM, GCS, Artifact Registry |

---

## 9. Agreed Approach Summary

1. **Phase 1:** Fix critical blockers (RegisterModel, ComponentConfig flatten, Environment overhaul, test infrastructure)
2. **Phase 2:** Unified task architecture refactor (`@task`/`@ml_task`, single Pipeline builder, smart compiler)
3. **Phase 3:** Cloud Build + Docker simplification (`gml build`, cloudbuild.yaml, 2-layer hierarchy)
4. **Phase 4:** Training pipeline E2E on GCP (prove it works end-to-end)
5. **Phase 5:** Complete pipeline + experiment tracking
6. **Phase 6:** Advanced features (for_each, condition, standard variables)
7. **Phase 7:** DBT integration
8. **Phase 8:** Polish (logging, mypy, docstrings, cost labels, AGENTS.md)

All phases follow TDD. All phases validated E2E on GCP. All commands use `uv run`. Framework treated as installable package.
