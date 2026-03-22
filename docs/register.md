# Model Registration — Design & Decisions

## Overview

`RegisterModel` uploads trained model artifacts to the Vertex AI Model Registry.
It is the **single owner** of the serving container image — `DeployModel` does
not need or accept serving image fields. This avoids duplication and ensures
there is one source of truth for which image serves a given model.

---

## Problem Statement

Two bugs surfaced during initial deployment:

1. **Single model name per pipeline.** The model display name was derived as
   `{team}-{project}-{branch}-{pipeline}`. A pipeline that trains two models
   (e.g., a regression model and a classifier) would overwrite or collide on
   the same display name.

2. **New artifact per registration.** Every call to `aiplatform.Model.upload()`
   created a brand-new top-level model resource instead of appending a version
   to an existing model. This cluttered the registry, broke version history,
   and made model comparison impossible.

---

## Vertex AI Model Registry Concepts

Vertex AI organises models into two levels:

| Concept | Description |
|---------|-------------|
| **Model (parent)** | A top-level resource identified by display name. Acts as a container for versions. |
| **Model Version** | An immutable snapshot of artifacts + metadata under a parent model. Versions are auto-numbered (v1, v2, ...). |

Key API parameters on `aiplatform.Model.upload()`:

- `display_name` — human-readable name. Used to *find* the parent model.
- `parent_model` — resource name of an existing model. When provided, the
  upload creates a **new version** under that parent instead of a new model.
- `is_default_version` — whether this version becomes the default when
  deployed. Defaults to `True`.
- `sync` — whether to wait for the upload to complete. We use `sync=False`
  to avoid LRO polling that consumes CRUD quota on shared projects.

---

## Fix 1: Multi-Model Support via `model_name`

### Problem

```
NamingConvention.vertex_model_name("house_price")
-> "mlplatform-third-run-main-house-price"
```

Two `RegisterModel` steps in the same pipeline produce identical names.

### Solution

Add a `model_name` field. When set, it's appended to the derived name:

```
vertex_model_name("house_price", "regression")
-> "mlplatform-third-run-main-house-price-regression"

vertex_model_name("house_price", None)
-> "mlplatform-third-run-main-house-price"   (backwards-compatible)
```

**Why a separate field instead of reusing `component_name`?**

- `component_name` is a display label for the KFP step (e.g., "Register Model").
  It has no naming-convention constraints and can contain spaces/caps.
- `model_name` is a slug that becomes part of the Vertex AI resource name. It
  must be deterministic across retrains (same name = same parent model).
- `model_name` is shared with `DeployModel` — it's the contract that links
  registration to deployment.

---

## Fix 2: Versioning via `parent_model`

### Problem

Every retrain creates a new top-level model:

```
mlplatform-third-run-main-house-price   (run 1)
mlplatform-third-run-main-house-price   (run 2)  <- duplicate
mlplatform-third-run-main-house-price   (run 3)  <- duplicate
```

### Solution

Before uploading, look up an existing model with the same display name.
If found, pass its `resource_name` as `parent_model`:

```python
existing = aiplatform.Model.list(
    filter=f'display_name="{model_display_name}"',
    project=project,
    location=region,
)
if existing:
    model = aiplatform.Model.upload(
        ...,
        parent_model=existing[0].resource_name,
        is_default_version=True,
        sync=False,
    )
else:
    model = aiplatform.Model.upload(..., sync=False)  # creates v1
```

**Result after three retrains:**

```
mlplatform-third-run-main-house-price-regression
  +-- v1  (run 1)
  +-- v2  (run 2)
  +-- v3  (run 3)  <- default
```

### Why `display_name` filter and not a stored model ID?

- The `display_name` is deterministic — derived from the naming convention.
  Same pipeline + same model_name always produces the same display name.
- Storing the model resource ID would require cross-run state management.
  The display name lookup is stateless.
- `aiplatform.Model.list(filter=...)` is a cheap metadata query.

### Why `sync=False`?

`Model.upload()` with `sync=True` (the default) polls the long-running
operation via repeated `GetOperation` calls. On shared GCP projects, this
consumes the 600 req/min CRUD quota and causes 429 ResourceExhausted errors.

`sync=False` returns immediately. The model is created asynchronously.
`DeployModel` handles this by looking up the model independently — it runs
as a separate pipeline step that executes after registration completes.

---

## Serving Image Ownership

`RegisterModel` is the **only** component that knows about the serving
container image. It captures the image in the Model Registry during upload
via `serving_container_image_uri`.

The serving image is resolved using a three-tier priority:

1. `serving_container_image` (full URI) — used as-is. Escape hatch for
   external or pre-built images.
2. `serving_dockerfile` (path relative to `docker/`) — resolved at compile
   time by the compiler into a full Artifact Registry URI.
3. Neither set — falls back to the default training image.

`DeployModel` does **not** have any serving image fields. It looks up the
already-registered model (which has the serving image baked in) and deploys
it. See `docs/deploy.md` for the deployment design.

---

## Edge Cases

### Branch Isolation

Because the display name includes the branch slug (`{team}-{project}-{branch}-...`),
models on different branches are separate parent models. Merging `feature/xyz`
to `main` and retraining creates the first version under the `main` parent —
no cross-branch contamination.

### Environment Promotion

When promoting from dev to staging/prod, the pipeline is recompiled with the
target environment's project ID and branch. This naturally creates a separate
parent model in the prod registry.

---

## Changes Summary

| File | Change |
|------|--------|
| `gcp_ml_framework/components/ml/register.py` | Added `model_name`, `serving_dockerfile` fields. `run()` does `Model.list()` + `parent_model` lookup. Uses `sync=False`. |
| `gcp_ml_framework/naming.py` | `vertex_model_name()` accepts optional `model_name`. |
| `gcp_ml_framework/pipeline/compiler.py` | Resolves `serving_dockerfile` to full URI for `RegisterModel` only. |
| `gcp_ml_framework/components/base.py` | `model_name` and `serving_dockerfile` in `_INTERNAL_FIELDS`. |
