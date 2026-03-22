# Model Registration — Design & Decisions

## Problem Statement

The `RegisterModel` component uploads trained model artifacts to the Vertex AI
Model Registry. Two bugs surfaced during initial deployment:

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
| **Model Version** | An immutable snapshot of artifacts + metadata under a parent model. Versions are auto-numbered (v1, v2, …). |

Key API parameters on `aiplatform.Model.upload()`:

- `display_name` — human-readable name. Used to *find* the parent model.
- `parent_model` — resource name of an existing model. When provided, the
  upload creates a **new version** under that parent instead of a new model.
- `is_default_version` — whether this version becomes the default when
  deployed. Defaults to `True`.
- `model_id` — optional user-specified ID for the parent model (set on first
  upload only). Useful for deterministic resource names.

---

## Bug 1: Model Name Doesn't Support Multiple Models Per Pipeline

### Current Behaviour

```
NamingConvention.vertex_model_name("house_price")
→ "mlplatform-third-run-main-house-price"
```

The compiler passes this as `model_display_name` to every `RegisterModel` in
the pipeline. Two `RegisterModel` steps in the same pipeline produce identical
names.

### Design Decision

Add an optional `model_name` field to `RegisterModel`. When set, it's appended
to the derived name:

```
vertex_model_name("house_price", "regression")
→ "mlplatform-third-run-main-house-price-regression"

vertex_model_name("house_price", None)
→ "mlplatform-third-run-main-house-price"   (backwards-compatible)
```

**Why a separate field instead of reusing `component_name`?**

- `component_name` is a display label for the KFP step (e.g., "Register Model").
  It has no naming-convention constraints and can contain spaces/caps.
- `model_name` is a slug that becomes part of the Vertex AI resource name. It
  must be deterministic across retrains (same name = same parent model).

**Pipeline usage:**

```python
pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(TrainRegressionStep(...))
    .add(RegisterModel(model_name="regression"))
    .add(TrainClassifierStep(...))
    .add(RegisterModel(model_name="classifier"))
    .build()
)
```

---

## Bug 2: Versioning — New Artifact vs New Version

### Current Behaviour

```python
model = aiplatform.Model.upload(
    display_name=self.model_display_name,
    artifact_uri=self.model_uri,
    serving_container_image_uri=self.serving_container_image,
)
```

Every retrain creates a new top-level model. The registry accumulates:

```
mlplatform-third-run-main-house-price   (run 1)
mlplatform-third-run-main-house-price   (run 2)  ← duplicate display name
mlplatform-third-run-main-house-price   (run 3)  ← duplicate display name
```

These are separate resources with separate resource IDs. There is no version
lineage between them.

### Design Decision

Before uploading, check if a model with the same display name already exists.
If so, pass its `resource_name` as `parent_model` to create a new version:

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
    )
else:
    model = aiplatform.Model.upload(...)  # creates v1
```

**Result after three retrains:**

```
mlplatform-third-run-main-house-price
  └── v1  (run 1)
  └── v2  (run 2)  ← default
  └── v3  (run 3)  ← default
```

### Why `display_name` filter and not a stored model ID?

- The `display_name` is deterministic — it's derived from the naming convention.
  Same pipeline + same model_name always produces the same display name.
- Storing the model resource ID (e.g., in GCS or as a pipeline output) would
  require cross-run state management. The display name lookup is stateless.
- `aiplatform.Model.list(filter=...)` is cheap (metadata query, no artifact
  transfer).

### Edge Case: Branch Isolation

Because the display name includes the branch slug (`{team}-{project}-{branch}-...`),
models on different branches are separate parent models. Merging `feature/xyz`
to `main` and retraining creates the first version under the `main` parent —
no cross-branch contamination.

### Edge Case: Environment Promotion

When promoting from dev to staging/prod, the pipeline is recompiled with the
target environment's project ID and branch. This naturally creates a separate
parent model in the prod registry. If you want to *copy* a model version
across projects instead, use `aiplatform.Model.copy()` (not handled by this
component — that's a promotion workflow concern).

---

## Changes Summary

| File | Change |
|------|--------|
| `gcp_ml_framework/components/ml/register.py` | Added `model_name` field. Updated `run()` to look up existing model and pass `parent_model`. |
| `gcp_ml_framework/naming.py` | Updated `vertex_model_name()` to accept optional `model_name` parameter. |
| `gcp_ml_framework/pipeline/compiler.py` | Pass `model_name` through to naming convention when set on `RegisterModel`. |
| `gcp_ml_framework/utils/vertex.py` | Same `parent_model` lookup in `run_deploy()`. |
| `gcp_ml_framework/components/base.py` | Added `model_name` to `_INTERNAL_FIELDS`. |
