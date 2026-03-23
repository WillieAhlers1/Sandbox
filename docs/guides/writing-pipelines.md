# Writing Pipelines

A pipeline is an ordered sequence of components defined in a single `pipeline.py` file. The framework compiles it to KFP YAML + Airflow DAG -- you never write either by hand.

## Pipeline Builder API

Use the `Pipeline` class with fluent `.add()` calls:

```python
from gcp_ml_framework import Pipeline

pipeline = (
    Pipeline(name="my_pipeline", schedule="@daily")
    .add(StepOne(...), name="Step One")
    .add(StepTwo(...), name="Step Two")
    .build()
)
```

`Pipeline()` parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | required | Pipeline directory name (must match the directory under `pipelines/`) |
| `schedule` | `str \| None` | `"@daily"` | Cron expression or Airflow preset. `None` for manually triggered only. |
| `description` | `str` | `""` | Human-readable description |
| `tags` | `list[str]` | `[]` | Tags for filtering in Airflow/Vertex UI |

`.add()` parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `component` | `BaseComponent` | Any component instance |
| `name` | `str \| None` | Display name (auto-generated from class name if not set) |

`.build()` returns a `PipelineDefinition` -- the frozen object passed to the compiler.

## Mixed Pipelines: @task + @ml_task

Pipelines can mix `@task` (Airflow operators) and `@ml_task` (Vertex AI containers). The SmartCompiler groups consecutive steps of the same type:

```python
pipeline = (
    Pipeline(name="training_pipeline", schedule="@daily")
    # --- @task group (compiled to Airflow operators) ---
    .add(BQQuery(
        sql="SELECT * FROM `{bq_dataset}.housing_data_table`",
        destination_table="training_raw",
        component_name="ingest_raw_data",
    ), name="Ingest Raw Data")
    .add(BQTransform(
        sql="SELECT *, CURRENT_TIMESTAMP() AS processed_at FROM `{bq_dataset}.training_raw`",
        output_table="training_features",
        component_name="transform_features",
    ), name="Transform Features")
    # --- @ml_task group (compiled to KFP YAML) ---
    .add(HouseTrainModelStep(
        component_name="train_house_model",
        runtime_dockerfile="pipelines/training_pipeline/base.Dockerfile",
    ), name="Train Model")
    .add(HouseEvaluateStep(
        metrics=["rmse", "mae", "r2"],
        gate={"rmse": 1_000_000},
        component_name="evaluate_house_model",
        runtime_dockerfile="pipelines/training_pipeline/base.Dockerfile",
    ), name="Evaluate Model")
    .add(RegisterModel(
        model_name="housing-predictor",
        runtime_dockerfile="pipelines/training_pipeline/base.Dockerfile",
        serving_dockerfile="pipelines/training_pipeline/serve.Dockerfile",
    ), name="Register Model")
    .add(DeployModel(
        model_name="housing-predictor",
        runtime_dockerfile="pipelines/training_pipeline/base.Dockerfile",
    ), name="Deploy Model")
    .build()
)
```

### How SmartCompiler handles this

The compiler scans step boundaries by `task_type` and produces:

```
[BQQuery, BQTransform]  -->  Airflow DAG operators (BigQueryInsertJobOperator x2)
                    |
                    v
[Train, Evaluate, Register, Deploy]  -->  KFP YAML + RunPipelineJobOperator in DAG
```

The generated DAG wires the operators sequentially: `ingest >> transform >> run_vertex_pipeline`. Data bridging between `@task` and `@ml_task` groups (e.g., passing a BQ table reference to the training step) is handled automatically by the compiler.

## `for_each()` Loops

Loop over a list of items, running the same steps for each. Only `@ml_task` components are supported in loops (Airflow operators cannot be dynamically unrolled at compile time).

```python
pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    .add(...)  # regular steps
    .for_each(
        items=["us-market", "eu-market"],
        steps=[
            TrainVerifyModelStep(
                component_name="train_market_variant",
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
            ),
        ],
        item_param="job_name",
    )
    .build()
)
```

Parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `items` | `list[str]` | Values to iterate over |
| `steps` | `list[BaseComponent]` | Components to run for each item (must be `@ml_task`) |
| `item_param` | `str` | Component field that receives the loop variable |
| `names` | `list[str] \| None` | Optional step names |

The `item_param` field must exist on the component class. For the example above, `TrainVerifyModelStep` inherits `job_name` from `TrainModel`.

The compiler generates a KFP `ParallelFor` that runs all items in parallel.

## `condition()` Branching

Execute steps conditionally based on a prior step's output. Only `@ml_task` components are supported in branches.

```python
pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    .add(EvaluateVerifyStep(...), name="Evaluate Model")
    .condition(
        source_step="Evaluate Model",
        operator="!=",
        value="",
        then_steps=[
            RegisterModel(
                model_name="verification-predictor",
                serving_dockerfile="pipelines/verification_pipeline/serve.Dockerfile",
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
            ),
            DeployModel(
                model_name="verification-predictor",
                runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
            ),
        ],
    )
    .build()
)
```

Parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_step` | `str` | Name of the step whose output to check |
| `output_key` | `str` | KFP output key to check (default: `"output_uri"`) |
| `operator` | `str` | Comparison: `==`, `!=`, `>`, `<`, `>=`, `<=` |
| `value` | `str` | Value to compare against |
| `then_steps` | `list[BaseComponent]` | Steps if condition is true |
| `else_steps` | `list[BaseComponent] \| None` | Steps if condition is false (optional) |

The compiler generates a KFP `dsl.If` block. In this example, registration and deployment only happen if the evaluation step produced a non-empty output (meaning the model passed quality gates).

## Dockerfile Fields

Every `@ml_task` component must set `runtime_dockerfile`. This tells the compiler which Docker image the component executes in.

```python
TrainModel(
    runtime_dockerfile="pipelines/house_price/base.Dockerfile",  # required
    ...
)
```

`RegisterModel` additionally accepts `serving_dockerfile` -- the image registered for serving in Vertex AI Model Registry:

```python
RegisterModel(
    runtime_dockerfile="pipelines/house_price/base.Dockerfile",
    serving_dockerfile="pipelines/house_price/serve.Dockerfile",
    ...
)
```

Dockerfile paths are relative to `docker/`. The compiler resolves them to full Artifact Registry URIs via `NamingConvention.docker_image_uri()`.

**Rules:**
- `runtime_dockerfile` must be set on every `@ml_task` component
- `serving_dockerfile` is only valid on `RegisterModel` -- it is the single owner of the serving image
- `@task` components do not need Dockerfiles (they run as native Airflow operators)

## The `model_name` Contract

`model_name` links registration to deployment. Both `RegisterModel` and `DeployModel` must use the same value:

```python
.add(RegisterModel(model_name="housing-predictor", ...))
.add(DeployModel(model_name="housing-predictor", ...))
```

The compiler derives from `model_name`:
- `model_display_name` -- used when uploading to Model Registry
- `endpoint_display_name` -- used when creating/updating the Vertex AI Endpoint

Format: `{namespace}-{pipeline}-{model_name}` and `{namespace}-{pipeline}-{model_name}-endpoint`

If `model_name` does not match, the deploy step will not find the registered model.

## Pipeline Directory Structure

Each pipeline lives under `pipelines/{name}/`:

```
pipelines/
  house_price/
    pipeline.py          # Pipeline definition (the only file you must have)
    steps/
      __init__.py
      train_regression_model.py   # Step subclasses
    sql/
      house_price_features.sql    # SQL files referenced by BQQuery/BQTransform
    seeds/                # Optional: seed data files
    config.yaml           # Optional: pipeline-specific config
```

The corresponding Docker files live under `docker/pipelines/{name}/`:

```
docker/
  base/
    base-python/
      Dockerfile         # Shared foundation (Python 3.12 + uv)
  pipelines/
    house_price/
      base.Dockerfile    # Pipeline execution image
      serve.Dockerfile   # Pipeline serving image
```

## Complete Example: Verification Pipeline

This pipeline demonstrates all features -- mixed tasks, loops, and conditions:

```python
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.transformation.dbt_run import DBTRun

pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    # Sequential @task steps (Airflow operators)
    .add(BQQuery(sql="SELECT * FROM `{bq_dataset}.housing_data_table`",
                 destination_table="verification_raw",
                 component_name="ingest_raw"), name="Ingest Raw Data")
    .add(BQTransform(sql="SELECT *, CURRENT_TIMESTAMP() AS processed_at"
                         " FROM `{bq_dataset}.verification_raw`",
                     output_table="verification_features",
                     component_name="transform_features"), name="Transform Features")
    .add(DBTRun(project_dir="/dbt", target="dev", models="marts.verification",
                component_name="dbt_transform"), name="DBT Models")
    # Sequential @ml_task steps (KFP)
    .add(TrainVerifyModelStep(
        component_name="train_verify_model",
        runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
    ), name="Train Model")
    .add(EvaluateVerifyStep(
        metrics=["rmse", "mae", "r2"], gate={"rmse": 1_000_000},
        component_name="evaluate_verify_model",
        runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
    ), name="Evaluate Model")
    # Loop: train per-market variants
    .for_each(
        items=["us-market", "eu-market"],
        steps=[TrainVerifyModelStep(
            component_name="train_market_variant",
            runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile",
        )],
        item_param="job_name",
    )
    # Condition: only register+deploy if eval passed
    .condition(
        source_step="Evaluate Model",
        operator="!=", value="",
        then_steps=[
            RegisterModel(model_name="verification-predictor",
                          serving_dockerfile="pipelines/verification_pipeline/serve.Dockerfile",
                          runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile"),
            DeployModel(model_name="verification-predictor",
                        runtime_dockerfile="pipelines/verification_pipeline/base.Dockerfile"),
        ],
    )
    .build()
)
```

Compilation result:
- `@task` steps (BQQuery, BQTransform, DBTRun) become native Airflow operators in the DAG
- `@ml_task` steps (Train, Evaluate) become a KFP YAML, triggered by `RunPipelineJobOperator`
- `for_each` produces a KFP `ParallelFor` inside the YAML
- `condition` produces a KFP `dsl.If` gating registration and deployment
