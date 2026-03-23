# Project: second_run

ML pipeline project built on the GCP ML Framework (`gcp_ml_framework`).

## Architecture

- **Unified task model:** `@task` (Airflow operators) and `@ml_task` (Vertex AI containers) decorators
- **Single Pipeline builder** with `.add()` API — data scientists define pipelines in one file
- **Smart compiler** auto-groups consecutive `@ml_task` steps into Vertex AI pipeline, wraps all in Airflow DAG
- **Environment via env var:** `ENVIRONMENT` (no prefix), set by CI/CD or `.env`. NOT derived from git branch.
- **Component lifecycle:** `cli()` → `execute()` → `run()`. Data scientists override `run()` only.
- **Per-pipeline Docker images:** `runtime_dockerfile` controls execution image, `serving_dockerfile` controls serving image
- **Full architecture doc:** `docs/architecture/overview.md` (14 sections, ASCII diagrams, process flows)

## Client Design Principles (PRs #23-#26) — NON-NEGOTIABLE

These are authoritative design decisions from the client. Violating any of these is a bug.

1. **`NamingConvention` is the single source of truth** for ALL GCP resource names. Python and bash both delegate to it. Never construct resource names outside `naming.py`.
2. **`RegisterModel` is the SINGLE OWNER of the serving container image.** `DeployModel` does NOT have serving image fields. No exceptions.
3. **`model_name` is the CONTRACT between `RegisterModel` and `DeployModel`.** Both must use the same value. The compiler derives matching `model_display_name` and `endpoint_display_name`.
4. **Two Dockerfiles per pipeline:** `base.Dockerfile` (execution) + `serve.Dockerfile` (serving). Root-level defaults (`docker/train.Dockerfile`, `docker/serve.Dockerfile`) are removed. Only `docker/base/base-python/Dockerfile` + `docker/pipelines/{name}/` remain.
5. **Docker image naming:** `{pipeline}--{stem}` delimiter via `NamingConvention.docker_image_name()`.
6. **Config simplified:** Single `GCP_PROJECT_ID` (not per-env). `FrameworkConfig` uses `env_prefix=""`, `GCPConfig` uses `env_prefix="GCP_"`.
7. **Registration vs Deployment separation:** RegisterModel captures image + artifacts. DeployModel looks up registered model by display name. No duplication.
8. **Generated DAGs must have ZERO `gcp_ml_framework` imports.** Self-contained Python files.
9. **`sync=False` on `Model.upload()`** to avoid CRUD quota exhaustion on shared GCP projects (see `docs/architecture/model-registry.md`).
10. **`enable_caching=False`** on `RunPipelineJobOperator` to prevent stale cache hits after teardown.

See `docs/architecture/model-registry.md` for full design rationale.

## Stack

- **Language:** Python 3.12
- **Package manager:** uv (exclusively — no pip, no poetry)
- **Pipeline orchestration:** KFP v2 on Vertex AI, triggered by Airflow (Cloud Composer)
- **Docker:** Per-pipeline images (`docker/pipelines/{name}/base.Dockerfile` + `serve.Dockerfile`). Built via Google Cloud Build.
- **Testing:** TDD. Three tiers — unit (mocked), integration (real GCP dev), e2e (full pipeline on Vertex AI)
- **Serving:** Per-pipeline FastAPI apps under `app/{pipeline}/app.py`
- **Logging:** loguru (not `print()`, not stdlib `logging`)

## Key Commands

```bash
# Install dependencies
uv sync

# Run CLI commands (loads .env)
UV_ENV_FILE=.env uv run -- gml <command>

# Compile pipelines to KFP YAML + Airflow DAG
UV_ENV_FILE=.env uv run -- gml compile --all

# Build Docker images via Cloud Build
UV_ENV_FILE=.env uv run -- gml build training_pipeline

# Deploy (compile + verify images + upload DAGs + upload YAML to GCS)
UV_ENV_FILE=.env uv run -- gml deploy --all

# Run pipeline locally against real GCP dev resources
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local

# Trigger deployed pipeline via Composer
UV_ENV_FILE=.env uv run -- gml run training_pipeline

# Run tests
uv run -- pytest tests/ -m unit -v

# Lint + type check
uv run -- ruff check gcp_ml_framework tests
uv run -- mypy gcp_ml_framework/
```

## Project Structure

- `gcp_ml_framework/` — Framework library (CLI, components, pipeline builder, compiler, naming)
- `pipelines/` — Pipeline definitions (each subdirectory has `pipeline.py` + `steps/`)
- `second_run/` — Shared business logic package (estimators, feature engineering)
- `app/` — Per-pipeline FastAPI serving apps (`app/{pipeline}/app.py`)
- `docker/` — Dockerfiles: `base/base-python/` (foundation), `pipelines/{name}/` (per-pipeline base + serve)
- `dags/` — Auto-generated Airflow DAGs (do not edit manually)
- `compiled_pipelines/` — Auto-generated KFP YAML (do not edit manually)
- `scripts/` — Build, bootstrap, and seed scripts
- `.env` — All config (team, project, GCP settings, environment) — gitignored
- `docs/` — `architecture.md`, `current_state_analysis.md`, `tasks/todo.md`, `register.md`, `deploy.md`

## Configuration

`.env` is the source of truth. Env var names:

| Variable | Prefix | Example |
|----------|--------|---------|
| `TEAM` | none | `mlplatform` |
| `PROJECT` | none | `second_run` |
| `ENVIRONMENT` | none | `local`, `dev`, `staging`, `prod` |
| `BRANCH` | none | auto-detected from git in local |
| `GCP_PROJECT_ID` | `GCP_` | `prj-my-sandbox` |
| `GCP_REGION` | `GCP_` | `us-east4` |
| `GCP_COMPOSER_DAGS_PATH` | `GCP_` | `gs://composer-bucket/dags` |
| `GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL` | `GCP_` | `sa@project.iam.gserviceaccount.com` |

- `FrameworkConfig` uses `env_prefix=""` — reads `TEAM`, `PROJECT`, `ENVIRONMENT`
- `GCPConfig` uses `env_prefix="GCP_"` — reads `GCP_PROJECT_ID`, `GCP_REGION`
- `get_git_branch()` is used ONLY for resource naming (branch isolation), NOT for environment resolution

## Key Relationships

- `runtime_dockerfile` (on ALL components) → Docker image the component **executes in** → resolved by compiler via `NamingConvention.docker_image_uri()`
- `serving_dockerfile` (on `RegisterModel` ONLY) → Docker image **registered for serving** in Vertex AI Model Registry
- `model_name` (on `RegisterModel` + `DeployModel`) → links registration to deployment. Compiler derives `model_display_name` and `endpoint_display_name` from it.
- `NamingConvention` → `{team}-{project}-{branch}` namespace → ALL GCP resource names derived from this
- `MLContext` → immutable runtime context constructed from `FrameworkConfig` → passed to compiler, components, CLI

## Important Notes

- Image tags are auto-derived as `{branch}-{short_sha}` by `naming.py` — never use `:latest`
- `dags/` and `compiled_pipelines/` are generated artifacts — regenerate with `gml compile` or `gml deploy`
- Local testing hits real GCP dev resources — NO DuckDB, NO mocks for `gml run --local`
- `house_price` pipeline is the reference implementation (correct API usage per client PRs)
- `training_pipeline` is the full ML lifecycle pipeline (ingest → transform → train → eval → register → deploy)
- `verification_pipeline` exercises ALL capabilities (loops, conditions, monitoring, mixed @task/@ml_task)
- Documentation: `docs/architecture/`, `docs/guides/`, `docs/operations/`, `docs/reference/`

---

# INSTRUCTIONS

## Quality Gates — Non-Negotiable

Every change MUST pass ALL of these before it is considered done:

1. **Ruff:** `uv run -- ruff check gcp_ml_framework tests` — zero errors, always
2. **Mypy:** `uv run -- mypy gcp_ml_framework/` — zero errors, 100% annotations, avoid `Any` unless the value is truly unconstrained
3. **Unit tests:** `uv run -- pytest tests/ -m unit -v` — all pass
4. **Local verification:** `UV_ENV_FILE=.env uv run -- gml compile --all` — compiles without error
5. **GCP verification:** For any change that touches GCP-interacting code, verify on dev: `UV_ENV_FILE=.env uv run -- gml run <pipeline> --local`

## Development Methodology

### TDD — Test-Driven Development
- Write tests FIRST, then implement
- Red → Green → Refactor
- Every new function, method, or behavior gets a test BEFORE the implementation
- If fixing a bug: write a test that reproduces the bug first, then fix it
- Never skip writing tests. No exceptions.

### Type Safety
- 100% mypy-strict annotations on all new code
- Never use `Any` unless the value is genuinely unconstrained (e.g., JSON deserialization output, third-party SDK return)
- When tempted to use `Any`, stop and ask: "Can I narrow this to a Protocol, Union, or concrete type?"
- Use `TYPE_CHECKING` imports for circular dependency avoidance
- Prefer `TypeVar` with bounds over `Any` for generic code

### Naming Conventions — DO NOT CHANGE
- Docker image naming: `NamingConvention.docker_image_name()` is the single source of truth
- GCP resource naming: all derived from `{team}-{project}-{branch}` namespace
- Dockerfile paths: `runtime_dockerfile` and `serving_dockerfile` are relative to `docker/`
- Component fields, method names, CLI flags — follow existing patterns exactly
- `RegisterModel` owns serving image. `DeployModel` does NOT. This is not optional.

### GCP Best Practices
- Catch specific GCP exceptions (`google.api_core.exceptions.NotFound`, etc.) — never bare `except Exception`
- Use `RunPipelineJobOperator` (not `CreatePipelineJobOperator`) for Airflow
- Use Artifact Registry (not deprecated Container Registry)
- Use Feature Store v2 (BQ-native), v1beta1 for FeatureGroup
- Cloud Build with `--cache-from` for layer caching
- `enable_caching=False` on RunPipelineJobOperator to prevent stale cache

## Workflow

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: capture the pattern in memory
- Write rules that prevent the same mistake
- Review lessons at session start

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Run quality gates (ruff, mypy, tests)
- Test locally AND on GCP dev for any GCP-touching change
- Ask yourself: "Would a staff engineer approve this?"

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- Skip this for simple, obvious fixes — don't over-engineer

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Write failing test first, then fix, then verify green

## Task Management

1. **Plan First**: Use plan mode for non-trivial tasks
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Verify Results**: Run quality gates before declaring done

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **TDD Always**: Test first, implement second, refactor third.
- **Type Everything**: 100% mypy annotations. No `Any` shortcuts.
- **Verify Everywhere**: Local + GCP dev. Both must work.
- **Client Design Is Law**: PRs #23-#26 design decisions are non-negotiable. See section above.
- **USE UV FOR PYTHON**
