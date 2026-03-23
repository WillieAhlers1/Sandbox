# Loop & Condition Operators — Design Document

## Status: DESIGN ONLY (implementation deferred)

## Problem Statement

Data scientists often need to train models per brand, market, or channel.
They need loop operators to reuse pipeline steps across multiple items,
and condition operators to gate deployment on metric thresholds.

## Proposed API

### for_each (Loop)

```python
pipeline = (
    Pipeline(name="multi_brand")
    .for_each(
        items=["brand_a", "brand_b", "brand_c"],
        steps=[
            TrainModel(component_name="train"),
            EvaluateModel(metrics=["auc"]),
        ],
    )
    .build()
)
```

### condition (Conditional)

```python
pipeline = (
    Pipeline(name="gated_deploy")
    .add(TrainModel(...))
    .add(EvaluateModel(metrics=["auc"], gate={"auc": 0.8}))
    .condition(
        predicate="metrics.auc > 0.8",
        then_steps=[RegisterModel(), DeployModel()],
    )
    .build()
)
```

## KFP Mapping

| Framework API | KFP DSL | Airflow |
|--------------|---------|---------|
| `.for_each(items, steps)` | `dsl.ParallelFor` | NOT SUPPORTED — raise `NotImplementedError` |
| `.condition(predicate, steps)` | `dsl.Condition` | NOT SUPPORTED — raise `NotImplementedError` |

## Airflow Limitation

@task steps (Airflow operators) cannot be unrolled at compile time.
If `for_each` or `condition` is used with @task steps, the compiler
must raise a clear `NotImplementedError` with message:
"Loop/condition operators are only supported for @ml_task steps (Vertex AI).
@task steps (Airflow operators) cannot be dynamically unrolled at compile time."

## Implementation Scope

This design document scopes the API and constraints. Implementation
requires changes to:
- `gcp_ml_framework/pipeline/builder.py` — add `for_each()` and `condition()` methods
- `gcp_ml_framework/pipeline/compiler.py` — handle `dsl.ParallelFor` / `dsl.Condition`
- `gcp_ml_framework/pipeline/smart_compiler.py` — raise error for @task steps

Implementation is deferred to a future phase.
