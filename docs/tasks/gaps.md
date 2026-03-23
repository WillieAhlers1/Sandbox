# Gaps & Remaining Work — Post-Audit 2026-03-23

**Baseline:** 244 tests pass, 0 fail. Ruff check clean. Mypy clean. All 3 pipelines compile.
**Branch:** `version_1_enc`

---

## CRITICAL

### C1. `.env` has wrong Artifact Registry repo name

**File:** `.env:38`
**Problem:** `GCP_AR_REPO=mlplatform-third-run` — project is `second_run`, repo should be `mlplatform-second-run`.
**Impact:** Any Docker operation using this env var targets the wrong registry.
**Fix:** Change to `GCP_AR_REPO=mlplatform-second-run`.

### C2. `training_pipeline` RegisterModel missing `model_name`

**File:** `pipelines/training_pipeline/pipeline.py:59-63`
**Problem:** `RegisterModel` has no `model_name` but `DeployModel` has `model_name="housing-predictor"`. PR #25 says `model_name` is the CONTRACT between Register and Deploy — both must use the same value.
**Fix:** Add `model_name="housing-predictor"` to RegisterModel.

### C3. `verification_pipeline` RegisterModel missing `model_name`

**File:** `pipelines/verification_pipeline/pipeline.py:66-69`
**Problem:** Same as C2. DeployModel has `model_name="verification-predictor"` but RegisterModel doesn't.
**Fix:** Add `model_name="verification-predictor"` to RegisterModel.

### C4. `training_pipeline` has no `runtime_dockerfile` on any component

**File:** `pipelines/training_pipeline/pipeline.py`
**Problem:** No component specifies `runtime_dockerfile`. Compiler falls back to `docker/train.Dockerfile` which was DELETED in PR #25. Compilation produces a URI string but deployment will fail — the image doesn't exist.
**Fix:** Create `docker/pipelines/training_pipeline/base.Dockerfile` and `serve.Dockerfile`. Add `runtime_dockerfile` and `serving_dockerfile` to pipeline definition (mirror `house_price` pattern).

### C5. `verification_pipeline` has no `runtime_dockerfile` on any component

**File:** `pipelines/verification_pipeline/pipeline.py`
**Problem:** Same as C4.
**Fix:** Create `docker/pipelines/verification_pipeline/base.Dockerfile` and `serve.Dockerfile`. Add `runtime_dockerfile` and `serving_dockerfile` to pipeline definition.

### C6. Compiler default dockerfile fallback references deleted file

**File:** `gcp_ml_framework/pipeline/compiler.py:216-222`
**Problem:** When `runtime_dockerfile` is None, `_resolve_image_uri()` falls back to `dockerfile_stem="train"` — i.e., `docker/train.Dockerfile`. That file was deleted in PR #25. Any component without explicit `runtime_dockerfile` will silently reference a non-existent image.
**Fix:** Either (a) require `runtime_dockerfile` explicitly (raise error if None), or (b) change default to the pipeline's `base.Dockerfile` using the pipeline name from context.

---

## MEDIUM

### M1. Ruff formatting — 49 files

**Problem:** `ruff format --check` fails on 49 files.
**Fix:** `uv run -- ruff format gcp_ml_framework tests`

### M2. `bq_query.py` missing `__main__` block

**File:** `gcp_ml_framework/components/operators/bq_query.py`
**Problem:** REQS 12.0 violation. Every component should have `if __name__ == "__main__": .cli()` for `--help` discoverability.
**Fix:** Append `if __name__ == "__main__": BQQuery.cli()`.

### M3. `.env` dead commented-out old env vars

**File:** `.env:1-19`
**Problem:** Entire block of commented-out OLD schema vars (`GML_TEAM`, `GML_GCP__DEV_PROJECT_ID`, etc.). Confusing — suggests old schema still works.
**Fix:** Delete lines 1-19.

### M4. `.env` dead `GCP_AR_HOST` and `GCP_AR_REPO` env vars

**File:** `.env:36-38`
**Problem:** `GCP_AR_HOST` and `GCP_AR_REPO` are not consumed by `config.py` (no matching fields in GCPConfig). They're not derived by `NamingConvention` either. Dead env vars that mislead.
**Fix:** Either (a) remove them (NamingConvention derives AR host/repo from project+region), or (b) add matching fields to GCPConfig if they're actually needed by `docker_build.sh`.

### M5. `training_pipeline` RegisterModel missing `serving_dockerfile`

**File:** `pipelines/training_pipeline/pipeline.py:59-63`
**Problem:** No `serving_dockerfile` on RegisterModel. No serving image gets registered for this pipeline. Only `house_price` has a `serve.Dockerfile`.
**Fix:** Create `docker/pipelines/training_pipeline/serve.Dockerfile` and add `serving_dockerfile` to RegisterModel (depends on C4).

### M6. `verification_pipeline` RegisterModel missing `serving_dockerfile`

**File:** `pipelines/verification_pipeline/pipeline.py:66-69`
**Problem:** Same as M5.
**Fix:** Create `docker/pipelines/verification_pipeline/serve.Dockerfile` and add `serving_dockerfile` to RegisterModel (depends on C5).

### M7. `docs/tasks/todo.md` is stale

**Problem:** Claims "105 pass, 61 fail, 60 errors" but reality is 244 passed, 0 failed. Most items marked incomplete are actually done. Misleading for anyone reading it.
**Fix:** Rewrite to reflect current state or replace with this gaps.md.

---

## LOW

### L1. `_INTERNAL_FIELDS` comment clarity

**File:** `gcp_ml_framework/components/base.py:27-29`
**Problem:** `_INTERNAL_FIELDS` includes `serving_dockerfile` and `model_name` which are NOT BaseComponent fields — they exist on subclasses (RegisterModel, DeployModel). Functionally correct (subclasses inherit the set) but confusing without explanation.
**Fix:** Add a comment: `# Includes subclass-only fields (serving_dockerfile, model_name) so they're excluded from KFP params on those subclasses`.

### L2. `feature_store/schema.py` docstring says "dataclasses"

**File:** `gcp_ml_framework/feature_store/schema.py:5`
**Problem:** Module docstring says "dataclasses" but implementation uses Pydantic BaseModel.
**Fix:** Update docstring.

### L3. `vertex.py` dead monitoring params

**File:** `gcp_ml_framework/utils/vertex.py:26-27`
**Problem:** `monitoring_skew_thresholds` and `monitoring_drift_thresholds` are accepted as parameters but never passed to the monitoring job creation in the function body.
**Fix:** Either wire them into the monitoring job config or remove the params.

### L4. `handler.py` may be dead code

**File:** `gcp_ml_framework/serving/handler.py`
**Problem:** Generic serving handler still exists alongside per-pipeline FastAPI apps (`app/{pipeline}/app.py`). PR #25 introduced per-pipeline serving. Handler.py may be dead but has passing tests.
**Fix:** Decide: keep as generic fallback or delete. If keeping, document when to use it vs per-pipeline apps.

### L5. Google-Style docstrings incomplete

**Problem:** REQS 10.0 [P2]. Most public methods have docstrings but some are missing — Email methods, some CLI helpers, some utility functions.
**Fix:** Audit all public methods and add Google-style docstrings where missing.

### L6. `.env` line 43-44 old schema reference

**File:** `.env:43-44`
**Problem:** Commented reference to `GML_GCP__COMPOSER_ENVIRONMENT_NAME` and `GML_GCP__COMPOSER_DAGS_PATH__DEV` — old env var names.
**Fix:** Delete these lines (cleaned up as part of M3).

---

## Execution Order

```
M1 (ruff format)           → trivial, do first
M2 (bq_query __main__)     → trivial, do first
M3 + M4 + L6 (clean .env)  → trivial, do together
C1 (fix AR repo name)      → trivial, do with .env cleanup
L1 + L2 (comment fixes)    → trivial

C6 (compiler default)      → small, do before C4/C5
C4 + C5 (pipeline dockerfiles) → medium, creates dirs + Dockerfiles
C2 + C3 + M5 + M6 (pipeline model_name + serving) → medium, updates pipeline.py files

L3 (vertex monitoring)     → small
L4 (handler.py decision)   → decision needed
L5 (docstrings)            → medium, can be done last
M7 (update todo.md)        → do after all fixes
```

---

## Not In Scope

| Item | Reason |
|------|--------|
| REQS 22.0 — Conditional & Loop Operators | Being implemented by another agent |
| REQS 16.0 — CI/CD Separation | Explicitly out of scope per user direction |
