# Pipeline Compilation

## Pipeline Builder API

Data scientists define pipelines in a single file using the fluent `Pipeline` builder. No KFP YAML, no Airflow DAG code, no operator wiring.

```python
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components import BQQuery, TrainModel, Email

pipeline = (
    Pipeline(name="churn-prediction", schedule="0 6 * * 1")
    .add(BQQuery(sql="SELECT ..."), name="Ingest")
    .add(TrainModel(machine_type="n2-standard-8"), name="Train")
    .add(Email(to=["team@co.com"], subject="Done"), name="Notify")
    .build()
)
```

### .add(component, name=None)

Appends a step. The `task_type` is read from the component's class (set by `@task` or `@ml_task` decorator). Name defaults to `{ClassName}_{index}`.

### .for_each(items, steps, item_param, names=None)

Parallel loop over a list of string items. Only `@ml_task` components are supported -- Airflow operators cannot be dynamically unrolled at compile time.

```python
@ml_task
class BrandTrainer(TrainModel):
    brand: str = ""

pipeline = (
    Pipeline(name="multi_brand")
    .for_each(
        items=["brand_a", "brand_b"],
        steps=[BrandTrainer(component_name="train")],
        item_param="brand",  # field on BrandTrainer that receives the loop variable
    )
    .build()
)
```

### .condition(source_step, operator, value, then_steps, else_steps=None)

Conditional branching based on a prior step's output. Only `@ml_task` components supported.

```python
pipeline = (
    Pipeline(name="conditional")
    .add(EvaluateModel(), name="Evaluate")
    .condition(
        source_step="Evaluate",
        output_key="output_uri",
        operator="!=",
        value="",
        then_steps=[RegisterModel(), DeployModel()],
        else_steps=[Email(to=["team@co.com"], subject="Model failed gate")],
    )
    .build()
)
```

Supported operators: `==`, `!=`, `>`, `<`, `>=`, `<=`.

### .build()

Returns a frozen `PipelineDefinition` containing:
- `steps` -- ordered list of `PipelineStep` objects
- `loop_blocks` -- `LoopBlock` objects from `.for_each()` calls
- `condition_blocks` -- `ConditionBlock` objects from `.condition()` calls
- `name`, `schedule`, `description`, `tags`

Properties:
- `has_mixed_types` -- True if pipeline contains both `@task` and `@ml_task` steps
- `has_control_flow` -- True if pipeline uses `for_each` or `condition` blocks
- `step_names` -- ordered list of step name strings

## SmartCompiler

`SmartCompiler` is the top-level compilation entry point. It analyzes task type boundaries and produces the right artifacts:

| Pipeline composition | Output |
|---------------------|--------|
| Pure `@ml_task` | 1 KFP YAML + thin Airflow DAG wrapper |
| Pure `@task` | Airflow DAG only, no YAML |
| Mixed `@task` + `@ml_task` | Airflow DAG with native operators + `RunPipelineJobOperator`(s) for ML groups |

### How Grouping Works

Steps are split into consecutive groups by `task_type` using `itertools.groupby`:

```
BQQuery → BQTransform → TrainModel → EvaluateModel → RegisterModel → Email
[------@task group------] [--------@ml_task group---------] [-@task-]
```

Each `@ml_task` group is compiled to a separate KFP YAML file via `PipelineCompiler`. The Airflow DAG then orchestrates all groups sequentially:

```
bq_query >> bq_transform >> run_vertex_pipeline >> email_notify
                            (RunPipelineJobOperator)
```

### Cross-Step Data Flow (Bridging)

When a `@task` group produces data that a subsequent `@ml_task` group needs, SmartCompiler bridges the gap:

1. `@task` steps with `destination_table` or `output_table` fields produce a deterministic BQ table reference (`project.dataset.table`)
2. This reference is injected into the `RunPipelineJobOperator`'s `parameter_values` as `dataset_uri`
3. Inside the KFP pipeline, `dataset_uri` flows through as a pipeline input parameter

Similarly, `model_uri` is tracked from `TrainModel`/`RegisterModel` outputs and bridged forward.

### DAG Generation

The generated Airflow DAG file:
- Has **zero** `gcp_ml_framework` imports (self-contained Python)
- Uses `RunPipelineJobOperator` for ML groups (with `enable_caching=False`)
- Uses native operators (`BigQueryInsertJobOperator`, `EmailOperator`) for `@task` steps
- Includes Jinja template support (`{{ ds }}`, `{{ ds_nodash }}`) for run dates
- Sets `deferrable=True` on Vertex AI operators to free Airflow worker slots
- Disables schedule in dev environment (`schedule=None`)

## PipelineCompiler

`PipelineCompiler` generates KFP v2 YAML from a `PipelineDefinition`. It is called by `SmartCompiler` for each `@ml_task` group.

### How KFP YAML is Generated

1. **Build context params** -- GCP project, region, branch, dataset, experiment name, etc. from `MLContext`
2. **Build derived params** -- per-step computed values:
   - `TrainModel`: `job_name`, `model_output_uri`
   - `RegisterModel`: `model_display_name`, `serving_container_image` (resolved from `serving_dockerfile`)
   - `DeployModel`: `model_display_name`, `endpoint_display_name`
   - `WriteFeatures`: `feature_view_id`, `feature_group_id`
3. **Build the `@dsl.pipeline` function** dynamically:
   - For each step, call `component.as_kfp_component()` to get the KFP function
   - Merge component fields + context params + derived params
   - Wire sequential dependencies via `.after(prev_task)`
   - Track outputs for cross-step data flow
4. **Compile** via `kfp.compiler.Compiler().compile()` to produce the YAML file

### Image Resolution

Every component's `runtime_dockerfile` is resolved to a full Artifact Registry URI:

```
runtime_dockerfile="pipelines/house_price/base.Dockerfile"
-> us-east4-docker.pkg.dev/my-project/team-project/house-price--base:main-abc1234
```

The path is parsed to extract `pipeline_name` and `dockerfile_stem`, then `NamingConvention.docker_image_uri()` constructs the full URI. The delimiter `--` separates pipeline name from stem.

### Cross-Step Data Flow (Within KFP)

Inside a KFP pipeline, outputs flow automatically:

- Steps with `dsl.OutputPath` produce outputs accessible via `task.outputs["output_uri"]`
- `TrainModel` and `RegisterModel` outputs are tracked as `last_model_output`
- Data-producing steps (BQ ingest, transform) are tracked as `last_dataset_output`
- `WriteFeatures` is treated as metadata-only and does not overwrite `last_dataset_output`
- Subsequent steps receive these tracked values as `model_uri` and `dataset_uri` parameters

The pipeline also accepts `dataset_uri` and `model_uri` as top-level input parameters for bridging from Airflow.

## Loop Compilation

`.for_each()` blocks compile to `dsl.ParallelFor`:

```python
with dsl.ParallelFor(items=["brand_a", "brand_b"], name="loop_0") as loop_item:
    # Each step gets loop_item injected into its item_param field
    task = component_fn(..., brand=loop_item)
```

- Steps within the loop run in parallel across items
- The loop variable is injected into the field specified by `item_param`
- Sequential dependencies within the loop body are preserved via `.after()`
- Only `@ml_task` components are supported (validated at both builder and compiler level)

## Condition Compilation

`.condition()` blocks compile to `dsl.If` / `dsl.Else`:

```python
source_output = task_map["Evaluate"].outputs["output_uri"]

with dsl.If(source_output != "", name="condition_0"):
    # then_steps
with dsl.Else(name="condition_0_else"):
    # else_steps
```

- The source step is looked up from `task_map` by name
- The comparison uses the specified operator and value
- Cross-step data flow (`model_uri`, `dataset_uri`) is wired into condition branches
- `else_steps` are optional

## LocalRunner

`LocalRunner` executes pipelines in-process for development and testing. This is the `gml run --local` path.

```
gml run training_pipeline --local
```

### How It Works

1. Builds the same context params and derived params as `PipelineCompiler`
2. For each step sequentially:
   - Merges component fields + context params + derived params + cross-step data
   - Instantiates a fresh component with merged params
   - Calls `component.execute()` directly (no containers, no KFP, no Airflow)
3. Tracks outputs for cross-step wiring using the same model/dataset flow logic

### Differences from Compiled Execution

| Aspect | LocalRunner | Compiled (Vertex AI + Airflow) |
|--------|-------------|-------------------------------|
| Execution | In-process Python | Containers on Vertex AI / Airflow operators |
| GCP resources | Real dev resources | Real target-env resources |
| Control flow | Not supported | `ParallelFor`, `If`/`Else` |
| Output passing | Direct field extraction | KFP `OutputPath` files |
| Parallelism | Sequential only | Parallel loops, concurrent operators |

`LocalRunner` raises `NotImplementedError` for pipelines with `for_each()` or `condition()` blocks. These require the full KFP runtime.

### Output Extraction

Since KFP's `output_uri_path` file mechanism is not available locally, `LocalRunner` extracts outputs directly from component fields:
- `TrainModel` -> `model_output_uri`
- `BQQuery` -> `project.dataset.destination_table`
- `BQTransform` -> `project.dataset.output_table`

## Compilation Flow Summary

```
pipeline.py (Pipeline builder)
    |
    v
PipelineDefinition
    |
    v
SmartCompiler.compile()
    |
    +-- Group steps by task_type
    |
    +-- For each @ml_task group:
    |       PipelineCompiler.compile()
    |           -> component.as_kfp_component() for each step
    |           -> kfp.compiler.Compiler() -> YAML
    |
    +-- Generate Airflow DAG
    |       -> @task steps -> native operators (render_operator())
    |       -> @ml_task groups -> RunPipelineJobOperator
    |       -> Sequential dependencies
    |       -> Cross-type bridging (dataset_uri, model_uri)
    |
    v
compiled_pipelines/{name}.yaml  +  dags/{dag_id}.py
```
