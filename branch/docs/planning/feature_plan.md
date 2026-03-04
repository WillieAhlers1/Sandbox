# Feature Plan — DAG Factory

> Branch: `feature_dagFactory` | Status: In Progress

## Problem

The current DAG factory wraps a single Vertex pipeline in an Airflow DAG. It cannot:
- Compose non-Vertex tasks (BQ queries, notifications, sensors)
- Express parallel tasks or conditional logic
- Handle pure ETL workflows without Vertex
- Run multi-pipeline DAGs

## Solution

A `DAGBuilder` DSL that mirrors `PipelineBuilder` but targets Composer DAGs.

### Architecture

```
dag.py (DSL)
    │
    ▼
DAGBuilder.build() → DAGDefinition (immutable)
    │
    ▼
DAGCompiler.compile() → Airflow DAG Python file
    │
    ▼
gml deploy dags → Composer GCS bucket
```

Two-level orchestration:
- **Composer** handles scheduling, task dependencies, non-ML tasks
- **Vertex AI** handles ML step execution, caching, GPU scheduling

### DAGBuilder DSL

```python
from gcp_ml_framework.dag.builder import DAGBuilder
from gcp_ml_framework.dag.tasks import BQQueryTask, VertexPipelineTask, EmailTask

dag = (
    DAGBuilder(name="daily_sales_etl", schedule="0 6 * * *")
    .task(BQQueryTask(
        name="extract_sales",
        sql="SELECT * FROM `{bq_dataset}.raw_sales` WHERE dt = '{{ ds }}'",
    ))
    .task(BQQueryTask(
        name="transform_features",
        sql_file="sql/sales_features.sql",
        depends_on=["extract_sales"],
    ))
    .task(VertexPipelineTask(
        name="train_model",
        pipeline="sales_forecast",
        depends_on=["transform_features"],
    ))
    .task(EmailTask(
        name="notify_team",
        to=["team@example.com"],
        subject="Pipeline complete",
        depends_on=["train_model"],
    ))
    .build()
)
```

### Task Components

| Task Type | Airflow Operator | Purpose |
|---|---|---|
| `BQQueryTask` | `BigQueryInsertJobOperator` | Run SQL queries |
| `VertexPipelineTask` | `VertexPipelineOperator` (custom) | Submit Vertex AI pipeline |
| `EmailTask` | `EmailOperator` | Send notifications |
| `SlackTask` | `SlackWebhookOperator` | Slack alerts |
| `SensorTask` | `ExternalTaskSensor` / `GCSObjectExistenceSensor` | Wait for conditions |
| `PythonTask` | `PythonOperator` | Custom Python functions |
| `SparkTask` | `DataprocSubmitJobOperator` | Spark jobs (future) |

### DAG Compiler

Generates a standalone Python file that:
1. Imports only Airflow + provider packages (no framework dependency at parse time)
2. Inlines all config values (no `load_config()` at DAG parse time)
3. Wires task dependencies from `depends_on` declarations
4. Sets DAG-level defaults (retries, timeout, alerting)

### Naming

| Resource | Pattern |
|---|---|
| DAG ID | `{namespace_bq}__{dag_name}` |
| Task ID | `{task_name}` (unique within DAG) |
| DAG file | `dags/{namespace_bq}__{dag_name}.py` |

### Implementation Phases

1. **Phase 1:** Core DSL — DAGBuilder, DAGDefinition, base task interface, BQQueryTask
2. **Phase 2:** DAGCompiler — generate valid Airflow DAG files, validate syntax
3. **Phase 3:** Task library — VertexPipelineTask, EmailTask, SensorTask
4. **Phase 4:** Advanced features — parallel tasks, conditional logic, task groups
5. **Phase 5:** CLI integration — `gml deploy dags` uses new compiler

### New Files

```
gcp_ml_framework/dag/
├── builder.py          # DAGBuilder DSL
├── compiler.py         # DAGDefinition → Airflow DAG file
├── factory.py          # (updated) backward-compat wrapper
├── operators.py        # VertexPipelineOperator (existing)
└── tasks/
    ├── __init__.py
    ├── base.py         # BaseTask ABC
    ├── bq_query.py     # BQQueryTask
    ├── vertex.py       # VertexPipelineTask
    ├── email.py        # EmailTask
    └── sensor.py       # SensorTask
```

### Design Decisions

| Decision | Rationale |
|---|---|
| Compile to static Python files | Avoids framework import at Airflow parse time — faster DAG parsing |
| `depends_on` explicit | Clearer than implicit sequential ordering for DAG-level tasks |
| Keep PipelineBuilder separate | PipelineBuilder → KFP (ML steps). DAGBuilder → Airflow (orchestration). Different concerns. |
| Two-level orchestration | Composer schedules/coordinates. Vertex handles ML compute. Each does what it's best at. |
