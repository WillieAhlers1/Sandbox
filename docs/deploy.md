# Model Deployment — Design & Decisions

## Overview

The deployment pipeline has two distinct steps with clear responsibilities:

1. **`RegisterModel`** — uploads model artifacts to Vertex AI Model Registry
   and captures the serving container image. This is the single point where
   the serving image is declared.
2. **`DeployModel`** — looks up the already-registered model by display name
   and deploys it to a Vertex AI Endpoint. It does **not** need any serving
   image information — that's already baked into the registered model.

This separation means `DeployModel` is a pure deployment concern: find the
model, find or create the endpoint, deploy.

---

## Registration vs Deployment — Why Separate Steps?

Early iterations had `DeployModel` re-uploading the model (calling
`Model.upload()` again with the serving image). This was redundant:

- The model was already registered by `RegisterModel`.
- Passing `serving_container_image` to both components created a maintenance
  burden — change the image in one place but forget the other.
- `DeployModel` had no business knowing about Docker images; its job is to
  deploy a registered model to an endpoint.

**Current design:** `RegisterModel` owns the serving image. `DeployModel`
looks up the model by display name (which includes the serving image) and
deploys it. No duplication, no drift.

---

## Endpoint Naming

Endpoint display names include all four dimensions to guarantee uniqueness
across projects, branches, pipelines, and models:

```
{project_name}-{branch}-{pipeline_name}-{model_name}-endpoint
```

Example:
```
mlplatform-third-run-main-house-price-regression-endpoint
```

This is derived by `NamingConvention.vertex_endpoint_name()` which accepts
both `pipeline_name` and `model_name`. The `model_name` parameter matches
the value passed to `RegisterModel(model_name=...)`, ensuring the deployment
targets the correct registered model.

---

## `model_name` Contract

`model_name` is the contract between `RegisterModel` and `DeployModel`.
The same identifier is used by the compiler to derive matching
`model_display_name` and `endpoint_display_name` values:

```python
pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(HouseTrainModelStep(
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .add(RegisterModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
        serving_dockerfile="pipelines/house_price/serve.Dockerfile",
    ))
    .add(DeployModel(
        model_name="regression",
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .build()
)
```

Note: `DeployModel` only needs `model_name` and `runtime_dockerfile` — no
serving image fields.

---

## Dockerfile Fields — `runtime_dockerfile` vs `serving_dockerfile`

Every component has a `runtime_dockerfile` field (required, inherited from
`BaseComponent`) that specifies the Docker image it **executes in**.

`RegisterModel` additionally has `serving_dockerfile` — the Docker image
**registered as the serving container** in Vertex AI Model Registry.

| Field | On | Purpose |
|-------|----|---------|
| `runtime_dockerfile` | All components | Image this component **runs in**. Required. |
| `serving_dockerfile` | `RegisterModel` only | Image **registered for serving**. |

Both are paths relative to `docker/` (e.g. `"pipelines/house_price/serve.Dockerfile"`).
The compiler resolves them to full Artifact Registry URIs.

`DeployModel` does **not** have `serving_dockerfile` — the serving image is
already captured in the Model Registry during registration.

`serving_container_image` (full URI) remains as an escape hatch on
`RegisterModel` that takes priority over `serving_dockerfile`.

---

## File Organisation

Serving applications live in a top-level `app/` directory, separate from
pipeline training code:

```
app/                                    # serving applications (FastAPI)
└── house_price/
    └── app.py

pipelines/
└── house_price/
    ├── pipeline.py                     # pipeline definition
    ├── config.yaml                     # pipeline config
    ├── sql/                            # SQL queries
    │   └── house_price_features.sql
    └── steps/                          # training steps
        └── train_regression_model.py

docker/
├── base/
│   └── base-python/
│       └── Dockerfile                  # python:3.12-slim + uv
└── pipelines/
    └── house_price/
        ├── base.Dockerfile             # extends base-python, installs framework + deps
        └── serve.Dockerfile            # extends base, adds FastAPI + uvicorn
```

### Why separate `app/` from `pipelines/`?

Initially serving code lived inside `pipelines/house_price/serve/` (pipeline-
centric layout). We moved it out because:

- **Different lifecycles.** Training code runs as short-lived KFP steps.
  Serving code runs as long-lived web services. Mixing them blurs boundaries.
- **Serving is not a pipeline step.** It doesn't subclass `BaseComponent` or
  run inside KFP. Keeping it in `pipelines/` was misleading.
- **Simpler Docker context.** `serve.Dockerfile` copies only `app/house_price/`
  without pulling in SQL, seeds, or training steps.
- **Clear ownership.** A data scientist modifying training logic doesn't
  accidentally break the serving app, and vice versa.

### Docker Image Hierarchy

```
base-python (python:3.12-slim + uv)
  └── base.Dockerfile (framework + deps + source code)
        └── serve.Dockerfile (+ FastAPI + uvicorn + app code)
```

We simplified from four Dockerfiles (root-level train, serve, plus pipeline-
specific train and serve) to just two per pipeline:

- `base.Dockerfile` — extends `base-python`, installs the framework, copies
  source code. Used by all training and registration steps.
- `serve.Dockerfile` — extends `base`, adds FastAPI + uvicorn, copies the
  serving app. Used as the serving container.

Root-level default Dockerfiles (`docker/train.Dockerfile`, `docker/serve.Dockerfile`)
were removed. Every pipeline explicitly declares its Dockerfiles via
`runtime_dockerfile` and `serving_dockerfile` — no implicit fallbacks.

### Serving Framework

Serving apps use **FastAPI** + **uvicorn**:

- Request/response validation via Pydantic models
- OpenAPI docs auto-generated at `/docs`
- Liveness check — model is loaded at startup; health endpoint returns 503
  until the model is ready
- Each app must implement the Vertex AI custom container contract:
  - `GET /health` — liveness check (env: `AIP_HEALTH_ROUTE`)
  - `POST /predict` — prediction (env: `AIP_PREDICT_ROUTE`)
  - Listen on port 8080 (env: `AIP_HTTP_PORT`)

---

## Deployment Flow

1. **RegisterModel** uploads model artifacts to Vertex AI Model Registry
   with the serving container image baked in.
2. **DeployModel** looks up the registered model by `model_display_name`,
   finds or creates an endpoint by `endpoint_display_name`, and deploys
   the model to it.
3. Both use the same `model_name` → naming convention → deterministic
   display names. No serving image or model URI needs to be passed between
   steps.

### Endpoint Reuse

`DeployModel` checks for an existing endpoint with the same display name
before creating a new one. On redeployment, the new model version is
deployed to the same endpoint with the specified traffic split.

---

## Changes Summary

| File | Change |
|------|--------|
| `gcp_ml_framework/components/base.py` | `runtime_dockerfile` (required). `serving_dockerfile` in `_INTERNAL_FIELDS`. |
| `gcp_ml_framework/components/ml/deploy.py` | Removed `serving_dockerfile`, `serving_container_image`, `model_uri`. Looks up registered model instead of re-uploading. |
| `gcp_ml_framework/components/ml/register.py` | `serving_dockerfile` field. Serving image captured during registration. |
| `gcp_ml_framework/utils/vertex.py` | `run_deploy()` now does `Model.list()` lookup instead of `Model.upload()`. |
| `gcp_ml_framework/naming.py` | `vertex_endpoint_name()` accepts `pipeline_name` + `model_name`. |
| `gcp_ml_framework/pipeline/compiler.py` | Serving image resolution only for `RegisterModel`. `DeployModel` gets display names only. |
| `docker/pipelines/house_price/base.Dockerfile` | Extends base-python, installs framework + deps. |
| `docker/pipelines/house_price/serve.Dockerfile` | Extends base, adds FastAPI + uvicorn + app code. |
| `app/house_price/app.py` | FastAPI serving app with `/health`, `/predict`, liveness check. |
