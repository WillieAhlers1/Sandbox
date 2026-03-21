# Project: second_run

ML pipeline project built on the GCP ML Framework (`gcp_ml_framework`).

## Architecture

- **Unified task model:** `@task` (Airflow operators) and `@ml_task` (Vertex AI containers) decorators
- **Single Pipeline builder** replaces both `PipelineBuilder` and `DAGBuilder`
- **Smart compiler** auto-groups consecutive `@ml_task` steps into Vertex AI pipeline, wraps all in Airflow DAG
- **Environment via env var:** `GML_ENVIRONMENT` (set by CI/CD), NOT derived from git branch
- **Component lifecycle:** `cli()` → `execute()` → `run()`. Data scientists override `run()` only.

## Stack

- **Language:** Python 3.12
- **Package manager:** uv (exclusively — no pip, no poetry)
- **Pipeline orchestration:** KFP v2 on Vertex AI, triggered by Airflow (Cloud Composer)
- **Infrastructure:** Terraform (per-environment under `terraform/envs/`)
- **CI/CD:** GitHub Actions (`.github/workflows/`)
- **Docker:** 2-layer hierarchy (`base-python` → `{pipeline-name}` image). Built via Google Cloud Build.
- **Testing:** Three-tier — unit (mocked), integration (real GCP), e2e (full pipeline on Vertex AI)

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

# Trigger deployed pipeline via Composer (default mode)
UV_ENV_FILE=.env uv run -- gml run training_pipeline

# Run tests
uv run -- pytest tests/ -m unit -v

# Terraform
cd terraform/envs/dev && terraform init && terraform plan
```

## Project Structure

- `gcp_ml_framework/` — Framework library (CLI, components, pipeline builder, compiler, naming)
- `pipelines/` — Pipeline definitions (each subdirectory is a pipeline with `pipeline.py`)
- `second_run/` — Shared business logic package (estimators, feature engineering)
- `docker/` — Dockerfiles: `base-python` (base layer), `pipeline/` (all deps + source)
- `dags/` — Auto-generated Airflow DAGs (do not edit manually)
- `compiled_pipelines/` — Auto-generated KFP YAML (do not edit manually)
- `terraform/` — Infrastructure as code (per-env: dev, staging, prod)
- `scripts/` — Build and bootstrap scripts
- `.env` — All config (team, project, GCP settings, environment) — gitignored
- `docs/discussion.md` — Architecture discussion log with all decisions
- `docs/tasks/` — Task tracking (todo.md, decisions.md, lessons.md)

## Important Notes

- `.env` is the source of truth for all config (team, project, GCP settings). All config comes from env vars.
- Image tags are auto-derived as `{branch}-{short_sha}` by `naming.py`.
- Environment is set via `GML_ENVIRONMENT` env var (values: LOCAL, DEV, TEST, STAGING, PROD, EXPERIMENT). Default: `dev`.
- `get_git_branch()` is used ONLY for resource naming (branch isolation), NOT for environment resolution.
- The dev environment uses pre-existing GCP service accounts (IAM module is skipped in `terraform/envs/dev/main.tf`).
- `project_name` contains underscores (`second_run`) — Terraform normalizes to hyphens via `local.project_slug` for GCP resource IDs.
- `dags/` and `compiled_pipelines/` are generated artifacts — regenerate with `gml compile` or `gml deploy`.
- Local testing hits real GCP dev resources — NO DuckDB, NO mocks for `gml run --local`.

---

# INSTRUCTIONS

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately – don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `docs/tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes – don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests – then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

1. **Plan First**: Write plan to `docs/tasks/todo.md` with checkable items
2. **Verify Plan**: Check in before starting implementation
3. **Track Progress**: Mark items complete as you go
4. **Explain Changes**: High-level summary at each step
5. **Document Results**: Add review section to `docs/tasks/todo.md`
6. **Capture Lessons**: Update `docs/tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.
- **USE UV FOR PYTHON and ENSURE RUFF HAS NO ERRORS WHEN EVER DEALING WITH PYTHON CODE**
