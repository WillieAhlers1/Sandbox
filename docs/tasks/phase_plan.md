# Phase Plan: Deploy Model Quota Fix — Undeploy Before Deploy

**Date:** 2026-03-23
**Branch:** version_1_enc
**Status:** Ready for implementation

---

## Problem

`run_deploy()` in `gcp_ml_framework/utils/vertex.py` creates or reuses an endpoint by display name, then calls `endpoint.deploy(model=model, ...)`. This **adds** the new model to the endpoint without removing the old one. After ~8 pipeline runs, the sandbox project hits:

```
ResourceExhausted: 429 DeployedCustomModelsPerProjectPerRegion 8
```

All subsequent deploys fail across ALL branches and ALL pipelines.

## Root Cause

`vertex.py:70` calls `endpoint.deploy()` which accumulates models on the endpoint. The endpoint may already have a previously deployed model. Each deploy consumes one `DeployedCustomModelsPerProjectPerRegion` quota slot. The quota is 8 for the sandbox project.

## Design Decision

A deploy is a **replacement**, not an accumulation. Per PR #25 design:
- Endpoints are deterministic (`{namespace}-{pipeline}-{model_name}-endpoint`)
- Same `model_name` → same endpoint → deploy replaces the previous model version
- This matches the `sync=False` precedent from PR #24 (framework manages GCP quota concerns)

## Scope

| File | Change |
|------|--------|
| `tests/utils/test_vertex.py` | Add 3 tests (TDD — written first) |
| `gcp_ml_framework/utils/vertex.py` | Add undeploy-before-deploy logic |

No changes to `deploy.py`, `compiler.py`, or pipeline definitions.

---

## Implementation — TDD

### Step 1: Write Failing Tests (Red)

Add to `tests/utils/test_vertex.py`:

**Test 1: `test_existing_models_undeployed_before_new_deploy`**
- Setup: endpoint has `gca_resource.deployed_models` with 1 existing deployed model (mock `id="old-dm-id"`)
- Action: call `run_deploy()`
- Assert: `endpoint.undeploy(deployed_model_id="old-dm-id")` was called BEFORE `endpoint.deploy()`
- Why: Proves the replacement behavior works

**Test 2: `test_no_undeploy_when_endpoint_is_fresh`**
- Setup: endpoint has `gca_resource.deployed_models` as empty list (new endpoint)
- Action: call `run_deploy()`
- Assert: `endpoint.undeploy` was NOT called, `endpoint.deploy` was called
- Why: Proves we don't crash on fresh endpoints

**Test 3: `test_multiple_existing_models_all_undeployed`**
- Setup: endpoint has 2 deployed models (`id="dm-1"` and `id="dm-2"`)
- Action: call `run_deploy()`
- Assert: `endpoint.undeploy` called twice (once per model), then `endpoint.deploy` called
- Why: Handles edge case of multiple stale models on an endpoint

### Step 2: Implement (Green)

In `gcp_ml_framework/utils/vertex.py`, between the endpoint get-or-create block (line 68) and `endpoint.deploy()` (line 70), add:

```python
# Undeploy existing models to free quota — deploy is a replacement, not accumulation
for deployed_model in endpoint.gca_resource.deployed_models:
    logger.info(
        "Undeploying existing model %s from endpoint %s",
        deployed_model.id,
        endpoint.resource_name,
    )
    endpoint.undeploy(deployed_model_id=deployed_model.id)
```

### Step 3: Refactor

- Ensure `undeploy()` call uses proper error handling — wrap in try/except for `google.api_core.exceptions.NotFound` (model may have been removed externally)
- Log clearly so pipeline operators can see what happened

### Step 4: Quality Gates

```bash
uv run -- pytest tests/utils/test_vertex.py -m unit -v        # New + existing tests pass
uv run -- pytest tests/ -m unit -v                             # Full suite passes
uv run -- ruff check gcp_ml_framework/utils/vertex.py tests/utils/test_vertex.py
uv run -- ruff format gcp_ml_framework/utils/vertex.py tests/utils/test_vertex.py
uv run -- mypy gcp_ml_framework/                               # Clean
UV_ENV_FILE=.env uv run -- gml compile --all                   # Compiles
```

### Step 5: GCP Cleanup + Verification

Before running on GCP, free the quota:

```bash
# List all endpoints in the region
gcloud ai endpoints list --project=prj-0n-dta-pt-ai-sandbox --region=us-east4 --format="table(name, displayName, deployedModels.len())"

# For each stale endpoint, undeploy models then delete
gcloud ai endpoints undeploy-model ENDPOINT_ID --project=prj-0n-dta-pt-ai-sandbox --region=us-east4 --deployed-model-id=DEPLOYED_MODEL_ID
gcloud ai endpoints delete ENDPOINT_ID --project=prj-0n-dta-pt-ai-sandbox --region=us-east4
```

Then:

```bash
UV_ENV_FILE=.env uv run -- gml build training_pipeline
UV_ENV_FILE=.env uv run -- gml deploy training_pipeline
# Wait 3 min for Composer sync
UV_ENV_FILE=.env uv run -- gml run training_pipeline
```

Monitor in Vertex AI Console — the deploy step should succeed without quota errors.

---

## Definition of Done

### Code
- [ ] 3 new unit tests in `tests/utils/test_vertex.py` — all pass
- [ ] `run_deploy()` undeploys existing models before deploying new model
- [ ] Error handling: `NotFound` on undeploy is caught and logged (non-fatal)
- [ ] All 265+ existing tests still pass
- [ ] ruff check clean
- [ ] ruff format clean
- [ ] mypy 0 errors

### GCP Verification
- [ ] Stale endpoints cleaned up (quota freed)
- [ ] `training_pipeline` runs end-to-end on GCP without quota error
- [ ] Deploy step creates/reuses endpoint and replaces model (not accumulates)
- [ ] Subsequent re-run of same pipeline succeeds (proves replacement works)

### Documentation
- [ ] `docs/tasks/phase_plan.md` documents the plan (this file)
- [ ] Commit pushed to `version_1_enc` remote

### Client Philosophy Alignment
- [ ] PR #25 compliant: endpoints are deterministic, deploy is replacement
- [ ] PR #24 precedent: framework manages quota concerns (`sync=False` pattern)
- [ ] NamingConvention still single source of truth for endpoint names
- [ ] No changes to DeployModel component API — fix is internal to `run_deploy()`
