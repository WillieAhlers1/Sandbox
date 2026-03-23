# Architecture Decision Records

**Project:** GCP ML Framework (`gcp_ml_framework`) — version_1
**Date:** 2026-03-20

Each decision follows ADR format: Context → Decision → Rationale → Consequences → REQS alignment.

---

## ADR-001: Unified Task Architecture (@task / @ml_task)

**Status:** Accepted
**REQS:** 11.0 (Simplify PipelineBuilder), 12.0 (CLI Entrypoints)

**Context:**
Data scientists face cognitive overload with two parallel systems:
- `PipelineBuilder` + `BaseComponent` for Vertex AI (ML compute)
- `DAGBuilder` + `BaseTask` for Airflow (orchestration)

They must decide "is this a DAG or Pipeline?", learn different base classes (`BaseComponent` vs `BaseTask`), different builders, and understand when to use hybrid DAG-wrapping-Pipeline patterns. `BigQueryExtract` and `BQQueryTask` both run BQ queries but exist in different systems.

**Decision:**
Unify into a single system:
- `@task` decorator = lightweight work (BQ queries, emails, DBT runs). Compiled to Airflow operators.
- `@ml_task` decorator = heavy ML compute (training, evaluation, deployment). Compiled to Vertex AI container components.
- Single `Pipeline` builder replaces both `PipelineBuilder` and `DAGBuilder`.
- Smart compiler auto-groups consecutive `@ml_task` steps into a Vertex AI pipeline and wraps everything in an Airflow DAG.

**Rationale:**
- Industry direction: Metaflow, Flyte, ZenML all use unified task abstractions with execution-target metadata
- Eliminates the `BigQueryExtract` vs `BQQueryTask` duplication
- Data scientists learn ONE concept: "I have tasks. ML tasks need compute. Framework handles the rest."
- Framework makes infrastructure decisions, not data scientists
- Codebase is small (~3700 lines, 1 pipeline) — refactoring now is 10x easier than after building 7 more phases on the old architecture

**Consequences:**
- Major refactor: ~20 files, ~1500-2000 lines changed
- `DAGBuilder`, `BaseTask`, `dag/tasks/*.py` deprecated and merged into unified system
- `PipelineBuilder` renamed to `Pipeline`
- Smart compiler must handle: grouping consecutive @ml_task steps, bridging data flow between Airflow and Vertex AI, edge cases like @ml_task→@task→@ml_task splitting
- All existing pipelines updated to new API
- All tests rewritten for new API

**Alternative rejected:** Light touch (rename PipelineBuilder, document that data scientists never touch DAGBuilder). Rejected: "We do things the right way."

---

## ADR-002: Environment Resolution Owned by CI/CD

**Status:** Accepted
**REQS:** 15.0 (Rename GitState), 16.0 (Separate CI/CD from Framework)

**Context:**
The framework currently reads git branch names to determine the deployment environment via `_resolve_git_state()`:
- `main` → STAGING
- `prod/*` → PROD_EXP
- `v[0-9]*` → PROD
- everything else → DEV

This couples the framework to specific git conventions. Inside Vertex AI containers, there's no `.git` directory — branch-based resolution never actually ran there. Teams with different branching strategies must modify framework code.

**Decision:**
- Remove `_resolve_git_state()` / `_resolve_environment()` entirely from framework
- `environment` becomes a direct field on `FrameworkConfig`, populated from `GML_ENVIRONMENT` env var
- Default: `dev` (safe for local development)
- CI/CD workflows set `GML_ENVIRONMENT` explicitly per deployment target
- `get_git_branch()` stays ONLY for resource naming (branch isolation)

**Rationale:**
- Industry standard: framework answers "what" (run this pipeline), deployment system answers "where" (in staging)
- Same pattern as Kubernetes: apps read `ENVIRONMENT` env var, Helm/ArgoCD sets it
- Testability: test staging behavior by setting env var, not faking git state
- Multi-team: teams choose their own branching conventions without touching framework code

**Consequences:**
- `config.py`: Delete `_resolve_git_state()`, make `environment` a FrameworkConfig field
- `GML_ENVIRONMENT` becomes a required-with-default env var
- `.env` for local dev: `GML_ENVIRONMENT=dev`
- CI/CD workflows: each sets `GML_ENVIRONMENT` explicitly
- `context.py`: `git_state` field → `environment` field
- All code referencing `git_state` updated

---

## ADR-003: Environment Enum Values

**Status:** Accepted
**REQS:** 15.0 (Rename GitState to Environment)

**Context:**
REQS specifies: Local, Dev, Stage, Test, Prod. Current code has: DEV, STAGING, PROD, PROD_EXP.

**Decision:**
Six environment values: `LOCAL`, `DEV`, `TEST`, `STAGING`, `PROD`, `EXPERIMENT`

| Value | Purpose | Resource namespace created? |
|---|---|---|
| LOCAL | Local development without GCP | No (limited functionality) |
| DEV | Feature branches, individual developer sandboxes | Yes |
| TEST | QA environment, shared test infrastructure | Yes |
| STAGING | Pre-production mirror, integration validation | Yes |
| PROD | Production | Yes |
| EXPERIMENT | A/B experiments against production data | Yes |

**Rationale:**
- `TEST` confirmed as QA environment by user
- `STAGING` preferred over `Stage` (industry standard, avoids noun/verb ambiguity)
- `EXPERIMENT` replaces `PROD_EXP` (clearer naming for production A/B experiments)
- `LOCAL` added for offline/limited development scenarios

**Consequences:**
- Each environment with `Yes` creates a full resource namespace (BQ dataset, GCS prefix, Feature Store views, DAG)
- `GCPConfig` needs `test_project_id` field (or TEST reuses dev project)
- `FrameworkConfig._validate_projects` updated for new enum values

---

## ADR-004: Three-Tier Testing Strategy

**Status:** Accepted

**Context:**
Need to balance test speed (for framework development) with test accuracy (for data scientist validation). Using only mocks risks divergence from real GCP behavior. Using only real GCP makes tests slow and requires credentials everywhere.

**Decision:**

| Tier | Scope | GCP? | Speed | When |
|---|---|---|---|---|
| Unit | Framework logic, component instantiation, compiler output, naming | Mocked | <30s | Every commit |
| Integration | Individual step `execute()` against real BQ/GCS | Real dev project | Minutes | Feature branch push |
| E2E | Full pipeline compile → build → deploy → run on Vertex AI | Real dev project | 5-10 min | Before merge |

Data scientist iteration via `gml run --local` always hits real GCP.

**Rationale:**
- No DuckDB or SQL translation layers — zero divergence risk
- Unit tests are fast and hermetic for framework development
- Integration and E2E tests validate real GCP interactions
- `execute()` code is identical locally and on Vertex AI

**Consequences:**
- Test directory organized by functionality (not tier)
- Pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`
- CI requires GCP credentials for integration/e2e tests
- `conftest.py` provides both mocked fixtures (unit) and real GCP fixtures (integration)

---

## ADR-005: Cloud Build for All Docker Builds

**Status:** Accepted
**REQS:** 18.0 (Docker Cloud Build Migration), 18.0b (Simplify Docker Hierarchy)

**Context:**
Current approach uses local `docker buildx` on developer machines and CI runners. GitHub Actions runners have limited resources (2 vCPU, 7GB RAM, 14GB disk). ML Docker images with heavy pip dependencies can exhaust these limits. Build cache is local — not shared between developers.

**Decision:**
Google Cloud Build as the **one and only** build method for all contexts (local dev, CI/CD).

- New `gml build` CLI command wraps `gcloud builds submit`
- `cloudbuild.yaml` defines multi-step build with AR layer caching (`--cache-from`)
- `.gcloudignore` excludes secrets/state from build context upload
- `docker buildx` kept as undocumented escape hatch only
- Docker Desktop NOT required on developer machines

**Rationale:**
- **No Docker needed:** Data scientists need only `gcloud` CLI (already required for GCP auth). Eliminates Docker Desktop licensing issues for companies >250 employees.
- **Shared layer cache:** First build installs pip deps (~5 min). Every subsequent build from ANY developer hits cached layers (~30-60s). With local Docker, each developer rebuilds from scratch.
- **Faster builds:** Cloud Build machines (up to 32 vCPU, 128GB RAM) vs developer laptops (thermal throttling) or GitHub Actions runners (2 vCPU).
- **Consistency:** Same build process everywhere. "It built on my machine" eliminated.
- **No local disk bloat:** ML images are 3-8GB. No local Docker image storage.
- **Cost not a concern** (confirmed by user). 120 free build-minutes/day, then $0.003/build-minute.

**Consequences:**
- New `gml build [pipeline | --all]` CLI command
- New `cloudbuild.yaml` and `.gcloudignore` files
- Terraform: Cloud Build SA needs `roles/artifactregistry.writer`, `roles/storage.objectAdmin`
- `gml deploy` updated to use `gml build` instead of `docker_build.sh`
- Docker image hierarchy simplified: `base-python` → `{pipeline-name}` (2 layers, component-base and base-ml merge)
- `scripts/docker_build.sh` kept but not the documented path

---

## ADR-006: DBT as First-Class Feature

**Status:** Accepted
**REQS:** 19.0 (DBT Integration Verification)

**Context:**
REQS 19.0 asks to verify Composer can trigger DBT jobs. DBT handles SQL transformations with dependency resolution, incremental loads, testing, and documentation. It complements (not replaces) Vertex AI Feature Store:
- DBT: computes feature tables in BQ (the transformation)
- Feature Store: catalogs and serves features online (the serving)

**Decision:**
Build first-class DBT support, not just verification:
- New `DbtRun` component with `@task` decorator (compiles to Airflow operator)
- Auto-generate `profiles.yml` from `.env` (environment-aware targets)
- `gml init pipeline --dbt` scaffolds DBT project structure
- Composer configured with `dbt-bigquery` PyPI package
- Reference `dbt/` project in training_pipeline

**Rationale:**
- DBT is the industry standard for SQL transformations in modern data stacks
- Our current `BQTransform` component runs raw SQL without dependency resolution, testing, or incremental loads
- DBT complements the framework — data scientists write SQL models, DBT handles the DAG, our framework orchestrates DBT + ML
- Not deferring because the user explicitly requested it

**Consequences:**
- New component: `DbtRun(BaseComponent)` with `@task` default
- DAG compiler updated to render DBT operator (BashOperator or CloudBuildRunBuildOperator)
- `profiles.yml` generation utility in framework
- Composer Terraform module updated with `dbt-bigquery` PyPI package
- `BQTransform` stays for simple SQL (not all teams use DBT)

---

## ADR-007: Experiment Tracking in Component Lifecycle

**Status:** Accepted

**Context:**
The `experiment_name` field exists on components but is unused in version_1. Data scientists currently have no way to compare runs with different hyperparameters without manually logging to spreadsheets.

**Decision:**
Auto-log to Vertex AI Experiments inside `TrainModel.execute()` and `EvaluateModel.execute()`:
- After `run()` completes: log hyperparameters (component fields) and outputs
- After evaluation: log metrics (accuracy, RMSE, etc.) and gate results
- Experiment run ID derived from `job_name` + `run_date`

**Rationale:**
- Table stakes for ML platforms
- Zero effort for data scientists (automatic in lifecycle)
- Vertex AI Experiments UI already exists — no custom UI needed
- `evaluate.py` already partially logs to experiments (best-effort)

**Consequences:**
- `TrainModel.execute()` updated with experiment logging after `run()`
- `EvaluateModel.execute()` updated with metrics logging
- `google-cloud-aiplatform` already a dependency
- Experiment name derived from `NamingConvention.vertex_experiment()`

---

## ADR-008: External Package Support Pattern

**Status:** Accepted

**Context:**
`second_run` contains model/business logic (estimators, feature engineering) shared across pipelines. Multiple data scientists and teams need to import shared packages in their pipeline steps.

**Decision:**
External packages work naturally with the container component pattern:
1. Package listed as dependency in `pyproject.toml`
2. Docker image installs all dependencies via `uv sync`
3. `@ml_task` step's `run()` imports from the package
4. Multiple pipelines share the same package
5. Different branches can pin different versions

**Rationale:**
- No framework changes needed — this is a property of the container component pattern
- Standard Python packaging: `uv add second_run` or add to `pyproject.toml`
- Scales to multiple teams with separate packages

**Consequences:**
- No framework code changes
- Documentation: explain the pattern in quickstart guide
- `pyproject.toml` structure already supports this (core deps + optional groups)

---

## ADR-009: Test Organization by Functionality

**Status:** Accepted

**Context:**
Traditional organization (`tests/unit/`, `tests/integration/`, `tests/e2e/`) groups by test tier. This scatters related tests across directories.

**Decision:**
Group tests by functionality:
```
tests/
├── config/              (config, context, naming, environment)
├── components/          (base, train, evaluate, register, deploy, bq_query, email, decorators)
├── pipeline/            (builder, compiler, smart_compiler, local_runner, unified_builder)
├── cli/                 (all CLI commands)
├── training_pipeline/   (step tests, integration, e2e)
└── conftest.py
```

**Update (Phase 2.5):** `tests/dag/` removed — DAG compiler tests replaced by SmartCompiler tests in `tests/pipeline/test_smart_compiler.py`.

Use pytest markers (`@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e`) to select by tier.

**Rationale:**
- When you change `compiler.py`, all related tests are in `tests/pipeline/`
- Markers let you still run only unit tests or only integration tests
- Easier to find what to update when a module changes

**Consequences:**
- Test discovery via `uv run -- pytest tests/ -m unit` (fast) or `uv run -- pytest tests/` (all)
- Each test file can contain a mix of unit and integration tests, marked accordingly

---

## ADR-010: Cost Labels on GCP Resources

**Status:** Accepted

**Context:**
No visibility into per-pipeline, per-branch, per-team costs. Leadership frequently asks "how much does pipeline X cost?"

**Decision:**
Apply standard labels to every GCP resource the framework creates:
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

**Rationale:**
- Zero effort for data scientists (framework applies labels automatically)
- Enables cost allocation via GCP billing export + BQ views
- High value for leadership with minimal implementation effort

**Consequences:**
- `NamingConvention` gets `resource_labels` property
- `VertexRunner.submit()` passes labels to PipelineJob
- Component `execute()` methods pass labels to BQ/GCS clients
- `cloudbuild.yaml` includes labels in substitutions
- Terraform resources already partially labeled

---

## ADR-011: Docker Image Hierarchy Simplification

**Status:** Accepted
**REQS:** 18.0b (Simplify Docker Image Hierarchy)

**Context:**
Current hierarchy has 3 base images: `base-python`, `component-base`, `base-ml`. With the unified architecture, there's no separate "component" vs "trainer" concept — every `@ml_task` container needs the full project.

**Decision:**
Simplify to 2 layers:
```
base-python:tag            (Python 3.12 + uv — cached, changes rarely)
  └── {pipeline-name}:tag  (base-python + all deps + source code — per pipeline)
```

`component-base` and `base-ml` merge into a single pipeline image that installs all extras.

**Rationale:**
- Unified architecture: every container runs the same code (framework + project)
- Fewer images to build, cache, and manage
- `component-base` was essentially `base-ml` minus scikit-learn — not a meaningful distinction
- Aligns with REQS 18.0b

**Consequences:**
- Delete `docker/base/component-base/Dockerfile`
- Rename `docker/base/base-ml/Dockerfile` → `docker/pipeline/Dockerfile`
- Update `cloudbuild.yaml` for 2-layer build
- Update `scripts/docker_build.sh` (escape hatch)
- Compiled YAML references single pipeline image
