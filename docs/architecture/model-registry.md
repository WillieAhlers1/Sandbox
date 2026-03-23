# Model Registration and Deployment

## Design Principle

The pipeline has two distinct steps with strict ownership boundaries:

1. **RegisterModel** -- uploads model artifacts to Vertex AI Model Registry and captures the serving container image. Single owner of the serving image.
2. **DeployModel** -- looks up the registered model by display name and deploys it to a Vertex AI Endpoint. No serving image fields. No model URI. Pure deployment concern.

## The model_name Contract

`model_name` is the contract between `RegisterModel` and `DeployModel`. Both components declare the same `model_name` value, and the compiler uses it to derive matching display names:

```python
pipeline = (
    Pipeline(name="house_price", schedule="@daily")
    .add(HouseTrainModelStep(
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .add(RegisterModel(
        model_name="regression",                                    # <- contract
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
        serving_dockerfile="pipelines/house_price/serve.Dockerfile",
    ))
    .add(DeployModel(
        model_name="regression",                                    # <- same value
        runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    ))
    .build()
)
```

The compiler derives:

| Derived field | Source | Example |
|---------------|--------|---------|
| `model_display_name` | `NamingConvention.vertex_model_name(pipeline, model_name)` | `mlplatform-second-run-main-house-price-regression` |
| `endpoint_display_name` | `NamingConvention.vertex_endpoint_name(pipeline, model_name)` | `mlplatform-second-run-main-house-price-regression-endpoint` |

When `model_name` is not set, the display name is derived from the pipeline name alone (backwards-compatible):

```
vertex_model_name("house_price")       -> "mlplatform-second-run-main-house-price"
vertex_model_name("house_price", None) -> "mlplatform-second-run-main-house-price"
```

This supports pipelines that register multiple models without collision:

```
vertex_model_name("house_price", "regression") -> "...-house-price-regression"
vertex_model_name("house_price", "classifier") -> "...-house-price-classifier"
```

## RegisterModel

### Serving Image Resolution (Three-Tier Priority)

The serving container image is resolved at compile time using this priority:

**1. `serving_container_image` (full URI)** -- used as-is. For external or pre-built images:

```python
RegisterModel(
    serving_container_image="us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest"
)
```

**2. `serving_dockerfile` (path relative to `docker/`)** -- resolved by the compiler into a full Artifact Registry URI via `NamingConvention.docker_image_uri()`:

```python
RegisterModel(
    serving_dockerfile="pipelines/house_price/serve.Dockerfile"
)
# Resolved to: us-east4-docker.pkg.dev/my-project/team-project/house-price--serve:main-abc1234
```

**3. Neither set** -- falls back to the pipeline's default training image. Appropriate for batch prediction where the serving runtime matches the training runtime.

The compiler resolves this in `_build_derived_params()`:

```python
if isinstance(comp, RegisterModel):
    extra["model_display_name"] = context.naming.vertex_model_name(pipeline_name, comp.model_name)
    if not comp.serving_container_image:
        if comp.serving_dockerfile:
            extra["serving_container_image"] = self._resolve_image_uri(context, comp.serving_dockerfile)
        elif default_image:
            extra["serving_container_image"] = default_image
```

### Versioning via parent_model

`RegisterModel.run()` looks up existing models by display name before uploading. If found, a new version is created under the existing parent:

```python
existing = aiplatform.Model.list(
    filter=f'display_name="{self.model_display_name}"',
    project=self.project, location=self.region,
)
if existing:
    parent_model = existing[0].resource_name
    model = aiplatform.Model.upload(
        ..., parent_model=parent_model, is_default_version=True, sync=False,
    )
else:
    model = aiplatform.Model.upload(..., sync=False)  # creates v1
```

After three retrains:

```
mlplatform-second-run-main-house-price-regression
  +-- v1  (run 1)
  +-- v2  (run 2)
  +-- v3  (run 3)  <- default
```

Why `display_name` filter instead of stored model ID:
- The display name is deterministic (derived from naming convention). Same pipeline + same `model_name` always produces the same display name.
- No cross-run state management needed. The lookup is stateless.

### sync=False + wait() Pattern

`Model.upload()` is called with `sync=False` to avoid polling the long-running operation via repeated `GetOperation` calls. On shared GCP projects, `sync=True` consumes the 600 req/min CRUD quota and causes 429 ResourceExhausted errors.

`model.wait()` is called immediately after to block until the upload completes, then the resource name is returned and written to `output_uri_path`.

```python
model = aiplatform.Model.upload(**upload_kwargs, sync=False)
model.wait()
return str(model.resource_name)
```

## DeployModel

`DeployModel` has no serving image fields. Its job is:

1. Look up the registered model by `model_display_name`
2. Find or create an endpoint by `endpoint_display_name`
3. Deploy with the specified `traffic_split`, `machine_type`, and replica counts

### Model Lookup

```python
existing_models = aiplatform.Model.list(
    filter=f'display_name="{model_display_name}"',
    project=project, location=region,
)
if not existing_models:
    raise ValueError(f"No registered model found with display_name='{model_display_name}'.")
model = existing_models[0]
```

### Endpoint Reuse

On redeployment, the same endpoint is reused:

```python
existing = aiplatform.Endpoint.list(
    filter=f'display_name="{endpoint_display_name}"',
    project=project, location=region,
)
endpoint = existing[0] if existing else aiplatform.Endpoint.create(
    display_name=endpoint_display_name, ...
)
endpoint.deploy(model=model, traffic_split={"0": traffic_split.get("new", 100)}, ...)
```

### Canary Deployments

`DeployModel` supports traffic splitting:

```python
DeployModel(
    model_name="regression",
    traffic_split={"new": 10, "current": 90},
)
```

Default is `{"new": 100}` (full cutover).

### Optional Model Monitoring

Enable with `enable_monitoring=True`:

```python
DeployModel(
    model_name="regression",
    enable_monitoring=True,
    monitoring_alert_email="team@company.com",
    monitoring_skew_thresholds={"feature_a": 0.3},
    monitoring_drift_thresholds={"feature_a": 0.2},
)
```

Monitoring is best-effort -- creation failures are logged but do not fail the pipeline.

## Dockerfile Fields

Every component has `runtime_dockerfile`. Only `RegisterModel` has `serving_dockerfile`.

| Field | On | Purpose |
|-------|----|---------|
| `runtime_dockerfile` | All components | Docker image this component **executes in** |
| `serving_dockerfile` | `RegisterModel` only | Docker image **registered for serving** in Vertex AI |
| `serving_container_image` | `RegisterModel` only | Full URI escape hatch (takes priority over `serving_dockerfile`) |

Both `runtime_dockerfile` and `serving_dockerfile` are paths relative to `docker/`. The compiler resolves them to full Artifact Registry URIs. Both are in `_INTERNAL_FIELDS` (not passed as CLI flags or KFP params).

`DeployModel` does **not** have `serving_dockerfile` or `serving_container_image`. The serving image is already captured in the Model Registry during registration.

## Docker Image Hierarchy

```
base-python (python:3.12-slim + uv)
  +-- base.Dockerfile (framework + deps + source code)
        +-- serve.Dockerfile (+ FastAPI + uvicorn + app code)
```

Per pipeline, under `docker/pipelines/{name}/`:
- `base.Dockerfile` -- used as `runtime_dockerfile` for all pipeline steps
- `serve.Dockerfile` -- used as `serving_dockerfile` for `RegisterModel`

## Branch Isolation

Display names include the branch slug (`{team}-{project}-{branch}-...`), so models on different branches are separate parent models. Merging a feature branch to `main` and retraining creates the first version under the `main` parent -- no cross-branch contamination.

## Environment Promotion

When promoting from dev to staging/prod, the pipeline is recompiled with the target environment's project ID and branch. This creates a separate parent model in the prod registry.

## File Organization

```
app/                                    # serving applications (FastAPI)
  house_price/
    app.py

pipelines/
  house_price/
    pipeline.py                         # pipeline definition
    steps/
      train_regression_model.py

docker/
  base/
    base-python/
      Dockerfile                        # python:3.12-slim + uv
  pipelines/
    house_price/
      base.Dockerfile                   # runtime image (all steps)
      serve.Dockerfile                  # serving image (RegisterModel only)
```

Serving apps implement the Vertex AI custom container contract:
- `GET /health` (env: `AIP_HEALTH_ROUTE`)
- `POST /predict` (env: `AIP_PREDICT_ROUTE`)
- Listen on port 8080 (env: `AIP_HTTP_PORT`)

## End-to-End Flow

```
1. TrainModel.execute()
   -> run() writes artifacts to _work_dir
   -> uploads to GCS (model_output_uri)
   -> outputs model_uri to next step

2. RegisterModel.execute()
   -> run() calls Model.upload() with:
      - artifact_uri = model_uri (from TrainModel)
      - serving_container_image_uri (resolved from serving_dockerfile)
      - display_name (derived from model_name via NamingConvention)
      - parent_model (if existing model found)
      - sync=False, then wait()
   -> outputs resource_name

3. DeployModel.execute()
   -> run() calls run_deploy() which:
      - Looks up model by model_display_name
      - Finds/creates endpoint by endpoint_display_name
      - Deploys with traffic_split
      - Optionally creates monitoring job
```

No serving image or model URI needs to be explicitly passed between steps. `model_name` + `NamingConvention` handles all the wiring.
