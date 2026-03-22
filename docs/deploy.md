# Model Deployment — Design & Decisions

## Overview

Each registered model is deployed as its own Vertex AI Endpoint (web service).
The `DeployModel` component handles deploying the latest model version to an
endpoint, with support for canary traffic splits.

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

## `model_name` Parameter

`DeployModel` accepts `model_name` — the same identifier used by
`RegisterModel`. This creates a contract between registration and deployment:

```python
pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(TrainRegressionStep(...))
    .add(RegisterModel(model_name="regression"))
    .add(DeployModel(model_name="regression"))
    .build()
)
```

The compiler uses `model_name` to derive both `model_display_name` (to find
the registered model) and `endpoint_display_name` (to find or create the
endpoint). This means `DeployModel` no longer needs an explicit
`endpoint_name` field — the naming convention handles it.

---

## Dockerfile Fields — Execution vs Serving

Every component has two distinct Docker concerns. To avoid confusion, the
framework uses separate, explicitly-named fields for each:

| Field | On | Purpose |
|-------|----|---------|
| `runtime_dockerfile` | All components (`BaseComponent`) | The image this component **executes in**. **Required** — every component must declare it. |
| `serving_dockerfile` | `RegisterModel` | The image **registered as the serving container** in Vertex AI Model Registry. |

Both are paths relative to the `docker/` directory (e.g.
`"pipelines/house_price/serve.Dockerfile"`). Internally, the compiler
extracts the Dockerfile stem and pipeline name to resolve the full
Artifact Registry URI via `NamingConvention.docker_image_uri()`.

`DeployModel` does **not** need a serving image — it looks up the
already-registered model (which has the serving image baked in) and
deploys it to an endpoint.

```python
# Training step runs in the pipeline base image
HouseTrainModelStep(runtime_dockerfile="pipelines/house_price/base.Dockerfile")

# Register model — captures the serving image in Model Registry
RegisterModel(
    model_name="regression",
    runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    serving_dockerfile="pipelines/house_price/serve.Dockerfile",
)

# Deploy model — looks up the registered model, no serving image needed
DeployModel(
    model_name="regression",
    runtime_dockerfile="pipelines/house_price/base.Dockerfile",
)
```

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
        ├── train_regression_model.py
        └── train_classifier.py

docker/
├── base/
│   └── base-python/
│       └── Dockerfile                  # python:3.12-slim + uv
└── pipelines/
    └── house_price/
        ├── base.Dockerfile             # extends base-python, installs framework + deps
        └── serve.Dockerfile            # extends base, adds FastAPI + uvicorn
```

### Why separate `app/`?

- **Clear separation of concerns.** Training code (`pipelines/`) and serving
  code (`app/`) have different lifecycles and dependencies.
- **Serving code is not a pipeline step.** It runs as a long-lived web service,
  not as a KFP component.
- **Simpler Docker COPY.** `serve.Dockerfile` copies `app/house_price/` without
  pulling in training steps or SQL.

### Docker Image Hierarchy

```
base-python (python:3.12-slim + uv)
  └── base.Dockerfile (framework + deps + source code)
        └── serve.Dockerfile (+ FastAPI + uvicorn + app code)
```

Serving Dockerfiles extend the pipeline's base image. This avoids
duplicating dependency installation and ensures the serving container has
the same framework + model code as the training container:

```dockerfile
ARG BASE_IMAGE=base
FROM ${BASE_IMAGE}

RUN /app/.venv/bin/pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY app/house_price/ /app/app/house_price/

EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "app.house_price.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

The build script resolves `ARG BASE_IMAGE=base` to the full AR URI of
the pipeline's base image.

### Serving Framework

Serving apps use **FastAPI** + **uvicorn**:

- FastAPI provides automatic request/response validation via Pydantic models
- OpenAPI docs auto-generated at `/docs`
- Async-ready for high-throughput inference
- Dependencies declared in `pyproject.toml` under `[project.optional-dependencies].serving`

Each serving app must implement these Vertex AI custom container endpoints:
- `GET /health` — health check (env: `AIP_HEALTH_ROUTE`)
- `POST /predict` — prediction (env: `AIP_PREDICT_ROUTE`)
- Listen on port 8080 (env: `AIP_HTTP_PORT`)

---

## Deployment Flow

1. **RegisterModel** uploads model artifacts to Vertex AI Model Registry
   with `model_name` in the display name.
2. **DeployModel** looks up the registered model by display name, finds or
   creates an endpoint by display name, and deploys the model to it.
3. Both use the same `model_name` → naming convention → deterministic
   display names, so no cross-step state needs to be passed.

### Endpoint Reuse

`DeployModel` checks for an existing endpoint with the same display name
before creating a new one. On redeployment, the new model version is
deployed to the same endpoint with the specified traffic split.

---

## Changes Summary

| File | Change |
|------|--------|
| `gcp_ml_framework/components/base.py` | Renamed `image_name` → `runtime_dockerfile` (required, execution image). Added `serving_dockerfile` to `_INTERNAL_FIELDS`. |
| `gcp_ml_framework/components/ml/deploy.py` | Added `model_name` and `serving_dockerfile` fields. Removed `endpoint_name` (derived by compiler). |
| `gcp_ml_framework/components/ml/register.py` | Added `serving_dockerfile` field. Updated docstring with clear execution vs serving distinction. |
| `gcp_ml_framework/naming.py` | Updated `vertex_endpoint_name()` to accept `pipeline_name` + `model_name`. |
| `gcp_ml_framework/pipeline/compiler.py` | Added `_parse_dockerfile_path()` to extract pipeline + stem from path. Serving image resolution uses `serving_dockerfile`, execution image uses `runtime_dockerfile`. |
| `pyproject.toml` | Added `[project.optional-dependencies].serving` with `fastapi` and `uvicorn`. |
| `docker/pipelines/house_price/base.Dockerfile` | Extends base-python, installs framework + deps. |
| `docker/pipelines/house_price/serve.Dockerfile` | Extends base, adds FastAPI + uvicorn + app code. |
| `app/house_price/app.py` | FastAPI serving app with `/health` and `/predict`. |
| `docs/deploy.md` | This document. |
