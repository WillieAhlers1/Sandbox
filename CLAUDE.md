# CLAUDE.md

This file provides project context for Claude Code. It is automatically loaded at the start of every session.

## Project Overview

This is the **GCP ML Framework** (`gcp-ml-framework`) — a Python library + CLI (`gml`) that lets data scientists define ML pipelines as Python code, run them locally, and promote them to GCP with a single command. Every GCP resource name encodes its origin: `{team}-{project}-{branch}`. No tagging — names *are* the metadata.

**Tech stack:** Python 3.11, UV (package manager), KFP v2, Vertex AI, BigQuery, Cloud Composer (Airflow), Vertex AI Feature Store (Bigtable-backed), GCP Secret Manager, Pydantic v2, Typer CLI, DuckDB (local stubs), pytest, ruff, mypy.

## Architecture — Key Concepts

- **Branch-based isolation:** Git branch → GCP namespace (`{team}-{project}-{branch}`). Branch type determines target environment (DEV/STAGE/PROD). No `if env == "prod"` anywhere.
- **Environment mapping:** `feature/*`, `hotfix/*` → DEV (ephemeral) | `main` → STAGE (persistent) | release tag → PROD (immutable) | `prod/*` → PROD experiments.
- **Pipeline DSL:** Data scientists only edit `pipelines/{name}/pipeline.py` using `PipelineBuilder`. This generates both KFP v2 pipelines and Composer DAGs.
- **Feature Store foundation:** All features organized around business entities (User, Item, Session). Schemas in `feature_schemas/*.yaml`.
- **Config layering:** `framework defaults → framework.yaml → pipeline/config.yaml → env vars → CLI flags` (Pydantic v2).

## Directory Structure

```
├── pipelines/              # User-defined pipelines (PipelineBuilder DSL)
├── components/             # Reusable KFP v2 components (ingestion, transform, ML)
├── dags/                   # Cloud Composer DAG definitions (auto-generated)
├── feature_schemas/        # Entity-centric YAML feature definitions
├── tests/unit/             # Unit tests
├── tests/integration/      # Integration tests
├── .github/workflows/      # CI/CD (ci-dev, ci-stage, promote, ci-prod-exp, teardown)
├── scripts/bootstrap.sh    # One-time GCP project setup
└── framework.yaml          # Project-level config
```

**Framework library** (pip-installable `gcp_ml_framework/`):
```
├── naming.py       # Namespace resolution + sanitization
├── config.py       # Pydantic config system
├── context.py      # MLContext — single runtime context object
├── pipeline/       # PipelineBuilder DSL, runner (local + Vertex)
├── components/     # BaseComponent ABC + built-ins
├── dag/            # DAG factory + custom operators
├── feature_store/  # Schema parser + client (write/read)
├── cli/            # Typer CLI (`gml` entrypoint)
├── secrets/        # SecretManagerClient
└── utils/          # GCP helpers, logging
```

## Common Commands

```bash
# Package management (UV — never use pip directly)
uv sync                           # Install all deps from lockfile
uv add <package>                  # Add a dependency
uv run pytest                     # Run tests via UV

# CLI
gml init --team dsci --project churn-pred --gcp-project my-gcp-project
gml run churn-prediction --local           # Local run (DuckDB stubs) — default if no flag
gml run churn-prediction --vertex          # Submit to Vertex AI
gml run churn-prediction --compile-only    # KFP YAML only (CI)
gml run --vertex --all                     # Run all pipelines on Vertex AI
gml deploy dags                            # Sync DAGs to Composer
gml deploy features user item              # Deploy feature schemas
gml promote --from main --to prod --resource model:churn-v1
gml teardown --namespace {branch_namespace}
gml context show                           # Show resolved namespace + GCP project
gml lint                                   # Naming convention enforcement

# Testing & linting
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run ruff check .
uv run mypy .
```

## Code Style & Conventions

- **Python 3.11**, strict mypy, ruff with 100 char line length.
- **Ruff rules:** `E, F, I, UP, B, SIM` enabled. `E501` (line length) and `B008` (Typer `typer.Option()` in defaults) are suppressed.
- Use `StrEnum` (not `str, Enum`) for string enums — Python 3.11+.
- Use `X | None` (not `Optional[X]`) for optional type annotations.
- **No hardcoded GCP project IDs, bucket names, or dataset names** in `.py` files. All must come from `MLContext`.
- **No `os.environ.get("ENV")`** style environment checks. Config is injected via Pydantic.
- **No `if env == "prod"`** anywhere in pipeline code. Git state determines environment.
- All GCP resource names follow the naming convention: `{team}-{project}-{branch}`.
- Branch sanitization: `/` → `--`, special chars stripped, lowercase, max 30 chars.
- BigQuery names use underscores (BQ constraint): `{team}_{project}_{branch_safe}`.
- Every component implements `BaseComponent` ABC with `as_kfp_component()`, `as_airflow_operator()`, and optionally `local_run()`.
- Secrets referenced as `!secret <name>`, resolved at runtime via GCP Secret Manager. Never in YAML or code.

## Naming Convention Quick Reference

| Resource | Pattern |
|---|---|
| Namespace | `{team}-{project}-{branch}` |
| GCS path | `gs://{team}-{project}/{branch}/` |
| BQ dataset | `{team}_{project}_{branch_safe}` |
| Vertex Experiment | `{namespace}` |
| Vertex Pipeline run | `{namespace}-{pipeline_name}-{timestamp}` |
| Composer DAG ID | `{namespace}--{dag_name}` |
| Feature View | `{entity}_{branch_safe}` |
| Docker image tag | `{branch_safe}-{sha}` |

## Implementation Phases (Current Plan)

1. **Phase 1 (Wk 1-2):** Package scaffold, naming, config, context, secrets, `gml init`
2. **Phase 2 (Wk 2-3):** Component library (BaseComponent, all built-ins, unit tests)
3. **Phase 3 (Wk 3-4):** Pipeline DSL, DAG factory, runners (local/vertex/compile-only)
4. **Phase 4 (Wk 4-5):** Feature Store integration (schema parser, client, deploy)
5. **Phase 5 (Wk 5-6):** CLI commands (deploy, promote, teardown, lint)
6. **Phase 6 (Wk 6-7):** CI/CD workflows, bootstrap script, e2e example, docs

## Important Warnings

- Never use `pip install` directly — use `uv add` or `uv sync`.
- Never use `sudo npm install -g` for any tooling.
- STAGE and PROD resources are never touched by automated teardown — only DEV ephemeral resources.
- PROD is never deployed to directly from source. Only validated STAGE artifacts are promoted via release tags.
- The `MLContext` is the single object passed into every component. No globals, no env var spaghetti.

## Reference

- Full plan: `plan.md` in repo root
- Config example: `framework.yaml`
- Pipeline DSL example: `pipelines/churn_prediction/pipeline.py`
- Feature schema example: `feature_schemas/user.yaml`
