# Requirements Status

## P0 (Critical)

| ID | Title | Status |
|----|-------|--------|
| 1.0 | Unified Component Lifecycle (container-based steps, cli/execute/run) | Done |
| 5.0 | Airflow DAG 403 Permission Denial (Composer SA needs aiplatform.user) | Done |
| 6.0 | Compiled YAML embeds full Python source (resolved by 1.0) | Done |
| 7.0 | Pydantic migration (dataclasses to BaseModel) | Not Started |
| 8.0 | Replace argparse with Typer | Not Started |
| 11.0 | Simplify PipelineBuilder API (single `.add()` method) | Not Started |
| 12.0 | Refactor CLI entrypoints for container components (resolved by 1.0) | Done |
| 13.0 | Flatten ComponentConfig into BaseComponent | Not Started |
| 14.0 | Expose standard variables in base components | Not Started |
| 15.0 | Rename GitState to Environment | Not Started |
| 21.0 | Missing Model Registry step (RegisterModel) | Not Started |
| 22.0 | Loop and conditional operators in PipelineBuilder | Not Started |

## P1 (Important)

| ID | Title | Status |
|----|-------|--------|
| 2.0 | Project name underscore normalization for GCP resources | Done |
| 3.0 | Clean out invalid DAGs from DAGs folder | Not Started |
| 4.0 | Docker build tag issue on main branch (always use branch-sha) | Not Started |
| 9.0 | Structured logging with loguru | Not Started |
| 16.0 | Separation of CI/CD and framework concerns | Not Started |
| 18.0 | Docker Build Cloud migration (gcloud builds submit) | Not Started |
| 18.1 | Simplify Docker image hierarchy (two-layer) | Not Started |

## P2 (Nice to Have)

| ID | Title | Status |
|----|-------|--------|
| 10.0 | Google-style docstrings | Not Started |
| 17.0 | Enforce mypy annotations | Not Started |

## Other (No Priority Assigned)

| ID | Title | Status |
|----|-------|--------|
| 19.0 | DBT integration verification | Not Started |
| 20.0 | Provide AGENTS.md for AI-assisted coding | Not Started |

## Summary

| Priority | Total | Done | Not Started |
|----------|-------|------|-------------|
| P0 | 12 | 4 | 8 |
| P1 | 7 | 1 | 6 |
| P2 | 2 | 0 | 2 |
| Other | 2 | 0 | 2 |
| **Total** | **23** | **5** | **18** |
