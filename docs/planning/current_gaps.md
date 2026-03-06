# Current Gaps

> Gaps identified through exhaustive repo review against `project_guideline.md`,
> `current_state.md`, `gcp_run_log.md`, and all source files.
>
> Date: 2026-03-06
> Branch: `os_experimental`
> Excludes CI/CD (Phase 6) which is a known, tracked gap.
> Updated: 2026-03-06 — resolved gaps marked with RESOLVED.

---

## Critical Gaps

### ~~1. `docker_build.sh` does not push images~~ — RESOLVED

`--push` flag added. `docker_build.sh --push` pushes all built images to AR.

### ~~2. `docker_build.sh` does not build or push base-python or base-ml~~ — RESOLVED

Script now builds the full hierarchy: base-python → base-ml + component-base →
trainer images.

### 3. `gml run --bq` mode documented but not implemented

**Location**: `gcp_ml_framework/cli/cmd_run.py`

No intermediate step between `--local` (DuckDB) and `--composer` (requires full
Composer environment). Users cannot validate SQL against real BigQuery without
deploying to Composer.

### ~~4. `bootstrap.sh` creates a generic SA, misaligned with Terraform~~ — RESOLVED

Bootstrap simplified to API enablement + AR repo creation only. SA creation
removed; Terraform handles IAM.

---

## Moderate Gaps

### ~~5. No `compute.googleapis.com` in bootstrap.sh~~ — RESOLVED

Added to the API list.

### ~~6. 4 failing tests (WriteFeatures data flow)~~ — RESOLVED

All tests pass. Fix was already in the codebase.

### ~~7. MEMORY.md has stale "sales_analytics dependency bug" entry~~ — RESOLVED

Stale entry removed from MEMORY.md.

### 8. Terraform state bucket hardcoded

**Location**: `terraform/envs/dev/main.tf` line 15-18

The GCS backend bucket is hardcoded to `gcp-gap-demo-terraform-state`. New users
cloning the repo will hit `terraform init` failures because they don't have
access to this bucket.

**Suggested fix**: Add a comment directing users to update it.

### ~~9. No `base-ml` Dockerfile build-args for AR base image~~ — RESOLVED

Both `base-ml/Dockerfile` and `component-base/Dockerfile` now accept
`ARG BASE_IMAGE=base-python:latest`. `docker_build.sh` passes `--build-arg`
automatically.

### ~~10. Stale DAG files in `dags/` directory~~ — NON-ISSUE

`dags/*.py` is already gitignored. `git ls-files dags/` returns nothing.

---

## Minor Gaps

### ~~11. `docker_build.sh` uses `BASE_IMAGE_TAG` for component-base tag~~ — RESOLVED

All images now tagged consistently with `IMAGE_TAG`.

### ~~12. No `--run-date` passed through local DAG runner~~ — RESOLVED

`_run_local()` now passes `run_date` to both `DAGLocalRunner.run()` and
`LocalRunner.run()`.

### 13. No automated end-to-end integration test for GCP

**Location**: `tests/` directory

All 431 tests run against mocks and DuckDB. There is no test that validates the
full compile -> deploy -> run -> verify cycle against a real GCP environment.

### ~~14. No `gml run --vertex` support for DAG-based pipelines~~ — RESOLVED (improved error)

`--vertex` now detects dag.py-only pipelines and gives a clear error directing
users to `--composer` or `--local`.

### ~~15. Missing `--run-date` flag documentation in `gml --help`~~ — RESOLVED

CLI help now includes seed data date alignment details.

### 16. Terraform AR repo name includes environment suffix

**Location**: `terraform/envs/dev/main.tf` line 92

TF creates `{team}-{project}-{env}` but framework expects `{team}-{project}`.
Deferred — current AR repo was created with the correct name via bootstrap.

---

## Summary

| Priority | Total | Resolved | Open |
|----------|-------|----------|------|
| Critical | 4 | 3 | 1 (--bq mode) |
| Moderate | 6 | 5 | 1 (TF state bucket) |
| Minor | 6 | 4 | 2 (GCP smoke test, TF AR naming) |

**Remaining open gaps**: 4 total (1 critical, 1 moderate, 2 minor).

**Not counted here**: CI/CD (Phase 6) is the single largest gap and is tracked
separately in `current_state.md`.
