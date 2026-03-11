# Current State Assessment

> Critical evaluation of platform completion against `project_guideline.md` goals.
> Date: 2026-03-11
> Branch: `test`
> Evaluated by: Full codebase review (all 51 source files, 19 test files, 4 Terraform modules, 3 use cases, all docs)

---

## Executive Summary

**Phases 1–5 are substantially complete. Phase 6 (CI/CD) has not been started.**

The framework core, all three use cases, Terraform infrastructure, Feature Store v2 integration, and testing are done. The platform has been proven on GCP with both the sales_analytics DAG on Composer and the churn_prediction pipeline on Vertex AI. However, the entire CI/CD layer (4 GitHub Actions workflows) — which is required for Goal G4 ("Zero manual infrastructure") — does not exist yet.

| Phase | Status | Detail |
|-------|--------|--------|
| Phase 1: Clean Foundation | **COMPLETE** | All dead code removed, CLI restructured, core interfaces updated |
| Phase 2: Three Use Cases + Docker + Local DAG Runner | **COMPLETE** | All 3 use cases work locally and compile cleanly |
| Phase 3: Feature Store + Model Management | **COMPLETE** | v2 APIs, model versioning, experiment tracking |
| Phase 4: Infrastructure (Terraform) | **COMPLETE** | All 4 modules, 3 env configs, validated and applied to dev |
| Phase 5: Testing | **COMPLETE** | 451 passing, 0 failing |
| Phase 6: CI/CD | **NOT STARTED** | No `.github/workflows/` directory exists |
| **New Project Migration** | **IN PROGRESS** | Deploying to `prj-0n-dta-pt-ai-sandbox` (us-east4). Phases 0-5 done (infra + Docker + seed data + local validation). Phase 6 (GCP deploy) next. See `docs/tasks/todo.md`. |

---

## Goal Achievement

| # | Goal | Status | Evidence |
|---|------|--------|----------|
| G1 | Minimal friction for data scientists | **Partially met** | CLI works (`gml run/compile/deploy`), local runs work, but CI/CD isn't there to automate the merge→staging→prod path |
| G2 | End-to-end orchestration | **Met** | All 3 pipelines proven on GCP. sales_analytics 7/8 on Composer, churn_prediction 6/6 on Vertex AI, recommendation_engine 3/4 on Composer+Vertex (notify fails — no SMTP). |
| G3 | Branch isolation | **Met** | All resources namespaced by `{team}-{project}-{branch}`. Naming convention enforced throughout. Teardown command exists. |
| G4 | Zero manual infrastructure | **NOT met** | Requires CI/CD workflows. Currently all builds, deploys, and Docker pushes are manual CLI operations. |
| G5 | Three proven use cases | **Met** | churn_prediction (pure ML), sales_analytics (fan-out/fan-in ETL), recommendation_engine (hybrid DAG+Vertex). All compile, all run locally, all verified on GCP. |

---

## What Works Well

### Framework Core (naming, config, context, secrets)
- `NamingConvention` correctly derives all GCP resource names from `{team}-{project}-{branch}`
- Pydantic v2 config with layered resolution (framework.yaml → env vars → CLI flags) works correctly
- Git state → environment mapping (feature/* → DEV, main → STAGING, v* → PROD) is solid
- Secret resolution with `!secret` references and local env var fallback works
- `gml context show` displays all resolved names accurately

### Two DSLs
- **PipelineBuilder**: Fluent DSL → PipelineDefinition → KFP v2 YAML works end-to-end. Compilation produces valid YAML. Vertex AI execution proven.
- **DAGBuilder**: Fluent DSL → DAGDefinition → Airflow Python file works end-to-end. Supports `depends_on` for arbitrary DAG shapes. Fan-out/fan-in pattern proven.
- Auto-wrapping: `pipeline.py` automatically gets wrapped in a single-task Composer DAG — data scientists never write Airflow code for pure ML.
- Generated DAGs are self-contained: zero `gcp_ml_framework` imports. Only standard Airflow + `airflow.providers.google`.

### Local Execution
- DuckDB-based local runner for both pipelines and DAGs works
- Seed data loaded from CSV files into DuckDB automatically
- BQ-to-DuckDB SQL translation handles backticks, `DATE_SUB`, `SAFE_DIVIDE`, `LOG1P`, `CURRENT_TIMESTAMP`, `FLOAT64→DOUBLE`
- `sales_analytics --local` runs all 8 tasks in topological order
- `recommendation_engine --local` runs the hybrid DAG including nested Vertex pipeline execution via `LocalRunner`
- `--dry-run` mode shows execution plan without running

### GCP Deployment (Proven)
- **sales_analytics on Composer**: 7/8 tasks SUCCESS (notify fails — no SMTP in DEV, expected). daily_report table has correct data (3 categories, proper revenue/refund/stock figures).
- **churn_prediction on Vertex AI**: All 6 steps SUCCEEDED. BQ tables populated, model trained, metrics logged to Experiments, model deployed to endpoint.
- **recommendation_engine on Composer + Vertex AI**: 3/4 tasks SUCCESS (extract_data, compute_features, train_model). notify fails — no SMTP. Both Vertex AI pipelines (reco_features, reco_training) completed successfully.
- Component-base Docker image optimization eliminates ~8-16 minutes of pip install overhead per pipeline run.
- Auth uses ADC correctly throughout — no hardcoded credentials or manual token fetching.
- `gml deploy` auto-retags AR images when commit SHA changes — no manual Docker rebuilds needed.

### Docker Hierarchy
- Three-tier image hierarchy (base-python → component-base / base-ml → trainer) is well designed
- `docker_build.sh` auto-generates Dockerfiles for pipelines with `trainer/` directories
- `TrainModel` auto-derives image URI from pipeline directory name

### Terraform
- All 4 modules implemented: composer, artifact_registry, iam, storage
- Composer 3 module uses correct `workloads_config` (not Composer 2 `node_config`)
- IAM module creates both Composer SA and Pipeline SA with correct roles
- WIF support for GitHub Actions OIDC is included
- Per-environment scaling: dev=SMALL, staging=SMALL, prod=MEDIUM
- `terraform validate` passes for dev (staging/prod need `terraform init` — no remote state bucket configured yet)
- Successfully applied to `gcp-gap-demo-dev` — Composer 3 environment, AR repo, GCS bucket, IAM all provisioned

### Testing
- 469 total tests (all passing)
- Comprehensive coverage: components (45), CLI (22), config/context/naming (45+15), DAG builder/compiler/tasks (67+1), pipeline builder/compiler (28), feature store/secrets/SQL (27), phase regression (112), integration E2E (25), component-base image (26), composer runner (8)
- All 3 use cases have E2E integration tests (compile + local run)
- Generated DAG validation (parseable, no framework imports)

---

## What Needs Work

### 1. CI/CD Workflows — NOT STARTED (Critical)

**Impact**: This is the single largest gap. Without CI/CD, Goal G4 ("Zero manual infrastructure") is unmet. The entire automated pipeline from PR → staging → prod does not exist.

**Missing files** (per project_guideline.md Section 12):
- `.github/workflows/ci.yaml` — PR validation (lint, type check, test, compile, docker build)
- `.github/workflows/cd-staging.yaml` — merge to main → deploy to staging
- `.github/workflows/cd-prod.yaml` — release tag → deploy to prod (with manual approval gate)
- `.github/workflows/teardown.yaml` — branch delete → clean up DEV resources

**What this means**: Currently, all Docker builds, compiles, deploys, and teardowns are manual CLI operations. A data scientist merging to main must manually run `gml compile --all`, `gml deploy --all`, and Docker builds.

### ~~2. Failing Tests (4 tests)~~ — RESOLVED

All 4 WriteFeatures data-flow tests now pass. 436 tests passing, 0 failing.

### ~~3. Triple-Brace Jinja Bug in Generated DAGs~~ — RESOLVED

Fixed in `gcp_ml_framework/dag/compiler.py`. Now generates valid `{{ ds_nodash }}` (double braces).

### ~~4. `churn_prediction --local` Fails Due to Gate Threshold~~ — RESOLVED

Previously failed with `auc=0.5000 < 0.78`. Now passes with `auc=1.0, f1=1.0` — `EvaluateModel` computes real sklearn metrics locally on the 10-row seed dataset (trivially learnable). All 3 pipelines run successfully locally.

### ~~5. Stale DAG Files from Previous Branch~~ — RESOLVED

Stale DEV-branch DAG files cleaned up. `dags/` is gitignored.

### 6. Terraform Backend Not Configured

No `backend.tf` file exists. The `terraform/envs/*/main.tf` files reference a local backend by default. For multi-environment usage, a GCS remote backend should be configured. The `docs/prerequisite/infrastructure.md` mentions this but it hasn't been set up.

Staging and prod environments haven't had `terraform init` run (expected — no GCP projects configured for those environments yet).

### 7. ReadFeatures in Same File as WriteFeatures

`ReadFeatures` is defined in `write_features.py` rather than having its own file. The `__init__.py` exports both, so imports work, but this is inconsistent with the project's file-per-component convention.

---

## Component-by-Component Status

### Framework Core

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| NamingConvention | `naming.py` | **Solid** | All naming patterns correct, BQ 30-char truncation, branch sanitization |
| Config | `config.py` | **Solid** | Pydantic v2, layered resolution, env var support |
| Context | `context.py` | **Solid** | Immutable runtime object, property delegation |
| Secrets | `secrets/client.py` | **Solid** | Secret Manager + local env var fallback, `!secret` resolution |
| SQL Compat | `utils/sql_compat.py` | **Solid** | 7 BQ→DuckDB translations, well-tested |
| BQ Utils | `utils/bq.py` | **Solid** | `NotFound` exception handling (was `except Exception`) |
| GCS Utils | `utils/gcs.py` | **Functional** | Basic operations |

### Components (KFP v2)

| Component | Status | Local Run | KFP Component | Notes |
|-----------|--------|-----------|---------------|-------|
| BigQueryExtract | **Solid** | DuckDB SQL | BQ query + GCS export | Template var resolution works |
| GCSExtract | **Functional** | Placeholder dir | GCS copy | Local is stub only |
| BQTransform | **Solid** | DuckDB SQL | BQ SQL + materialize | `sql_file` support works |
| WriteFeatures | **Solid** | Pass-through input_path | FeatureGroup registration | Tests pass, local_run returns input_path correctly |
| ReadFeatures | **Functional** | DuckDB read | BQ read | Falls back to empty DataFrame |
| TrainModel | **Solid** | Placeholder model | Custom Training Job | Auto image resolution works |
| EvaluateModel | **Solid** | Placeholder metrics | Real sklearn metrics + gate | `start_run()` fix applied |
| DeployModel | **Functional** | Stub endpoint | Model Registry + Endpoint | Canary traffic split supported |

### Pipeline Engine

| Component | Status | Notes |
|-----------|--------|-------|
| PipelineBuilder | **Solid** | Fluent DSL, step sequencing, all 8 stage methods |
| PipelineCompiler | **Solid** | KFP v2 YAML, dual-track data flow (dataset/model), component-base image wiring |
| LocalRunner | **Solid** | WriteFeatures chain works, `pipeline_name` passed in kwargs |
| VertexRunner | **Functional** | Proven on GCP |

### DAG Engine

| Component | Status | Notes |
|-----------|--------|-------|
| DAGBuilder | **Solid** | Fluent DSL, `depends_on`, cycle detection, validation |
| DAGCompiler | **Solid** | Jinja fixed, deferrable=True for Vertex tasks |
| DAGLocalRunner | **Solid** | Topological execution, DuckDB, nested Vertex pipeline support |
| DAGFactory | **Solid** | Auto-discovery, pipeline.py auto-wrapping |
| BQQueryTask | **Solid** | Inline SQL + `sql_file`, template resolution |
| EmailTask | **Solid** | Console output in local, EmailOperator in compiled DAG |
| VertexPipelineTask | **Solid** | Accepts PipelineDefinition, compiles to RunPipelineJobOperator |

### CLI

| Command | Status | Notes |
|---------|--------|-------|
| `gml context show` | **Works** | `--json`, `--branch` flags |
| `gml run --local` | **Works** | Both pipeline.py and dag.py, `--dry-run`, `--run-date` |
| `gml run --vertex` | **Works** | `--sync`, `--no-cache` |
| `gml run --composer` | **Works** | Triggers via Airflow REST API |
| `gml run --bq` | **Works** | Direct BQ execution for DAG SQL |
| `gml compile` | **Works** | Single name + `--all` |
| `gml deploy` | **Works** | Single name + `--all`, `--dry-run` |
| `gml init project` | **Works** | Scaffolds framework.yaml, dirs |
| `gml init pipeline` | **Works** | Creates pipeline template; `--dag` for Composer DAG |
| `gml teardown` | **Works** | DEV-only safety, `--confirm` |

### Infrastructure

| Module | Status | Notes |
|--------|--------|-------|
| Composer 3 | **Works** | `google_composer_environment`, workloads_config, env size scaling |
| Artifact Registry | **Works** | Docker repo |
| IAM | **Works** | Composer SA + Pipeline SA + WIF |
| Storage | **Works** | GCS bucket with versioning |
| Dev env (original) | **Applied** | Provisioned on `gcp-gap-demo-dev` (us-central1) |
| Dev env (new) | **Applied** | Provisioned on `prj-0n-dta-pt-ai-sandbox` (us-east4). Storage + AR only (shared Composer). |
| Staging env | **Config only** | terraform.tfvars exists, not applied |
| Prod env | **Config only** | terraform.tfvars exists, not applied |

---

## Quantitative Summary

| Metric | Value |
|--------|-------|
| Python source files | 51 |
| Lines of framework code | ~4,700 |
| Test files | 20 |
| Total tests | 469 (all passing) |
| Test pass rate | 100% |
| Use cases implemented | 3 of 3 |
| CLI commands | 6 (all working) |
| Components (KFP v2) | 8 (all implemented) |
| DAG task types | 3 (all implemented) |
| Terraform modules | 4 (all implemented) |
| CI/CD workflows | 0 of 4 |
| GCP-proven pipelines | 3 of 3 (sales_analytics, churn_prediction, recommendation_engine) |

---

## Priority Action Items

### Must-Do (Blocking project goals)

1. **Create CI/CD workflows** (Phase 6) — `.github/workflows/{ci,cd-staging,cd-prod,teardown}.yaml`. This is the only remaining phase and is required for Goal G4.

### ~~Should-Do~~ — All resolved

2. ~~Fix triple-brace Jinja bug~~ — RESOLVED
3. ~~Fix the 4 failing tests~~ — RESOLVED (436 passing, 0 failing)
4. ~~Delete stale DAG files~~ — RESOLVED

### Nice-to-Have (Polish)

5. ~~Improve churn_prediction local run UX~~ — RESOLVED (real sklearn metrics on seed data now pass gate)

6. **Configure Terraform remote backend** — Add `backend "gcs"` configuration for state management across environments.

7. **Move ReadFeatures to its own file** — Consistent with file-per-component convention.

---

## Conclusion

The platform is **~90-95% complete** against its stated goals. All three use cases are proven on GCP (Composer + Vertex AI), 469 tests pass with 100% pass rate, and the full dev lifecycle (compile → deploy → run) works end-to-end.

The critical remaining work is **CI/CD (Phase 6)** — four GitHub Actions workflow files that automate the build/test/deploy lifecycle. Without these, the platform requires manual operations for what should be automated. Once CI/CD is in place, the platform achieves all five stated goals.
