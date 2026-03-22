# Phase 5: Complete ML Lifecycle — Training, Evaluation, Deployment & Monitoring

**Goal:** Expand both pipelines to the full 6-step ML lifecycle (ingest → transform → train → evaluate → register → deploy), add experiment tracking, and optional model monitoring. This proves the framework handles the complete data-scientist journey end-to-end.

**Starting state:** Phase 4.5 complete. 147 passing unit tests, ruff clean. verification_pipeline has 3 steps (BQQuery → BQTransform → TrainModel). training_pipeline has 1 step (TrainModel only).

**TDD discipline:** For every sub-task: write tests → watch them fail → implement → watch them pass → ruff check.

**Package manager:** `uv` exclusively. Never use pip or python directly.

**Test runner:** `uv run -- pytest tests/ -m unit -v`

**Linter:** `uv run -- ruff check gcp_ml_framework/ tests/`

---

## Table of Contents

1. [5.1 — Fix run_deploy() for Smart Model Resolution](#51)
2. [5.2 — Fix run_evaluate() for Regression Models](#52)
3. [5.3 — Add Experiment Tracking to TrainModel](#53)
4. [5.4 — Add Experiment Tracking to EvaluateModel](#54)
5. [5.5 — Add Monitoring Fields to DeployModel](#55)
6. [5.6 — Update run_deploy() and DeployModel for Monitoring](#56)
7. [5.7 — Create Evaluation Step Subclass for Housing](#57)
8. [5.8 — Add serving_container_image Defaults to Compiler](#58)
9. [5.9 — Wire Full training_pipeline (6 Steps)](#59)
10. [5.10 — Expand verification_pipeline (6 Steps)](#510)
11. [5.11 — Fix LocalRunner & Compiler Cross-Step Wiring](#511)
12. [5.12 — Tests](#512)
13. [5.13 — Full E2E Verification (6-Step Pipelines)](#513)
14. [5.14 — BQQuery Output Tracking](#514)
15. [5.15 — @task → @ml_task Data Bridging in SmartCompiler](#515)
16. [5.16 — Mixed Execution Scenario Test](#516)
17. [5.17 — Full E2E Verification (Mixed + Bridging)](#517)

---

## Architecture Overview

### Target Pipeline Shape (Both Pipelines)

```
BQQuery(@task) → BQTransform(@task) → TrainModel(@ml_task) → EvaluateModel(@ml_task) → RegisterModel(@ml_task) → DeployModel(@ml_task)
```

### SmartCompiler Output

The SmartCompiler groups consecutive same-type steps:

```
Group 1: [@task, @task]           → 2 native BigQuery Airflow operators in DAG
Group 2: [@ml_task × 4]          → 1 RunPipelineJobOperator in DAG → 4 containers in KFP YAML
```

Compiled Airflow DAG will have 3 tasks: `ingest_raw_data >> transform_features >> run_vertex_pipeline_1`

KFP YAML will have 4 container steps: train → evaluate → register → deploy (sequential via cross-step data wiring).

### Cross-Step Data Flow

**Two execution contexts with different wiring:**

**In KFP (compiled pipeline) — @ml_task steps only:**
```
[BRIDGED from Airflow via parameter_values]
  └─ dataset_uri = "{project}.{dataset}.training_features" (from last @task step's output)

TrainModel.execute()
  └─ reads from known table (self.dataset + ".training_features") — hardcoded in step subclass
  └─ writes model GCS URI to output_uri_path
  └─ KFP sets last_model_output = output

EvaluateModel.execute()
  └─ receives model_uri ← last_model_output (from TrainModel)
  └─ receives dataset_uri ← bridged value from Airflow (or constructs from self.dataset + table name as fallback)
  └─ writes metrics JSON to output_uri_path
  └─ KFP sets last_dataset_output = output

RegisterModel.execute()
  └─ receives model_uri ← last_model_output (GCS path from TrainModel)
  └─ writes resource_name to output_uri_path
  └─ KFP sets last_model_output = output (resource_name — per 5.11 fix)

DeployModel.execute()
  └─ receives model_uri ← last_model_output (resource_name from RegisterModel)
  └─ run_deploy() detects "projects/" prefix → skips re-upload, uses existing model
```

**In LocalRunner — all steps in-process:**
```
BQQuery.execute()
  └─ writes "{project}.{dataset}.{destination_table}" to output_uri_path
  └─ sets last_dataset_output = output

BQTransform.execute()
  └─ writes "{project}.{dataset}.{output_table}" to output_uri_path
  └─ sets last_dataset_output = output (e.g., "prj.dataset.training_features")

TrainModel.execute()
  └─ reads from known table (step subclass hardcodes table name)
  └─ writes model GCS URI to output_uri_path
  └─ sets last_model_output = output

EvaluateModel.execute()
  └─ receives model_uri ← last_model_output (GCS path)
  └─ receives dataset_uri ← last_dataset_output (from BQTransform — full table path)
  └─ writes metrics JSON to output_uri_path

RegisterModel.execute()
  └─ receives model_uri ← last_model_output (GCS path)
  └─ writes resource_name to output_uri_path
  └─ sets last_model_output = output (per 5.11 fix)

DeployModel.execute()
  └─ receives model_uri ← last_model_output (resource_name)
  └─ smart resolution in run_deploy()
```

**Key insight:** LocalRunner wires everything automatically because all steps run in-process. The KFP compiler needs explicit bridging (5.15) to pass @task outputs as KFP pipeline parameters. Step subclasses should also have a fallback: construct eval table from `self.dataset + ".table_name"` for robustness.

### Key Decision: DeployModel model_uri Source

**Option A (Current wiring):** DeployModel gets `model_uri` from `last_model_output` (TrainModel's GCS path). `run_deploy()` re-uploads to Model Registry — creating a duplicate of what RegisterModel already registered.

**Option B (Smart resolution):** Fix `run_deploy()` to detect `projects/` prefix → use existing registered model. Fix compiler/LocalRunner so DeployModel gets RegisterModel's output (resource_name) via `model_uri`.

**Decision: Option B.** The RegisterModel step exists precisely to avoid duplicate uploads. DeployModel should consume RegisterModel's output.

**Implementation:** The compiler currently injects `last_model_output` into any step with a `model_uri` field. RegisterModel's output goes to `last_dataset_output`. To fix this:
- Change compiler and LocalRunner: after RegisterModel, update `last_model_output` (not `last_dataset_output`) since its output IS a model reference
- OR: Add a `registered_model_name` field to DeployModel, wired from RegisterModel's output via `last_dataset_output`

**Chosen approach:** Update compiler/LocalRunner to set `last_model_output` from RegisterModel's output. This is cleaner — DeployModel.model_uri naturally receives the registered model resource_name, and run_deploy() handles both GCS paths and resource names.

---

<a id="51"></a>
## 5.1 — Fix run_deploy() for Smart Model Resolution

### Current State

`run_deploy()` in `gcp_ml_framework/utils/vertex.py` always calls `aiplatform.Model.upload()` with the provided `model_uri` as `artifact_uri`. This re-uploads the model to the registry even if `RegisterModel` already registered it.

### Target State

`run_deploy()` detects the format of `model_uri`:
- If it starts with `projects/` → it's a Vertex AI Model resource name → use `aiplatform.Model(model_uri)` directly
- If it starts with `gs://` → it's a GCS path → upload via `aiplatform.Model.upload()` (current behavior)

### Implementation

**File:** `gcp_ml_framework/utils/vertex.py`

```python
def run_deploy(
    *,
    project: str,
    region: str,
    model_uri: str,
    model_display_name: str,
    endpoint_display_name: str,
    serving_container_image: str,
    machine_type: str,
    min_replica_count: int,
    max_replica_count: int,
    traffic_split: dict[str, int],
    output_uri_path: str,
) -> None:
    aiplatform.init(project=project, location=region)

    # Smart model resolution
    if model_uri.startswith("projects/"):
        # Already registered — use existing model
        logger.info("Using registered model: %s", model_uri)
        model = aiplatform.Model(model_uri)
    else:
        # GCS path — upload to registry
        logger.info("Uploading model from %s", model_uri)
        model = aiplatform.Model.upload(
            display_name=model_display_name,
            artifact_uri=model_uri,
            serving_container_image_uri=serving_container_image,
        )

    # Get or create endpoint (unchanged)
    endpoints = aiplatform.Endpoint.list(
        filter=f'display_name="{endpoint_display_name}"',
    )
    if endpoints:
        endpoint = endpoints[0]
        logger.info("Reusing endpoint: %s", endpoint.resource_name)
    else:
        endpoint = aiplatform.Endpoint.create(display_name=endpoint_display_name)
        logger.info("Created endpoint: %s", endpoint.resource_name)

    # Deploy model to endpoint
    endpoint.deploy(
        model=model,
        machine_type=machine_type,
        min_replica_count=min_replica_count,
        max_replica_count=max_replica_count,
        traffic_split={"0": traffic_split.get("new", 100)},
    )

    if output_uri_path:
        Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_uri_path).write_text(endpoint.resource_name)
```

### Tests

**File:** `tests/utils/test_vertex.py`

```python
@pytest.mark.unit
def test_run_deploy_with_resource_name(mock_aiplatform):
    """When model_uri starts with 'projects/', skip upload and use Model() directly."""
    run_deploy(model_uri="projects/my-proj/locations/us-east4/models/123", ...)
    mock_aiplatform.Model.assert_called_once_with("projects/my-proj/locations/us-east4/models/123")
    mock_aiplatform.Model.upload.assert_not_called()

@pytest.mark.unit
def test_run_deploy_with_gcs_path(mock_aiplatform):
    """When model_uri starts with 'gs://', upload via Model.upload()."""
    run_deploy(model_uri="gs://bucket/models/v1", ...)
    mock_aiplatform.Model.upload.assert_called_once()
    mock_aiplatform.Model.assert_not_called()
```

### Verification

- Unit test: both code paths exercised
- Ruff clean

---

<a id="52"></a>
## 5.2 — Fix run_evaluate() for Regression Models

### Current State

`run_evaluate()` in `gcp_ml_framework/utils/evaluate.py` assumes binary classification:
- Uses `predict_proba()` if available, else `predict()`
- Thresholds at 0.5 for binary predictions
- Default metrics: `["auc"]`
- Drops columns `["label", "user_id", "feature_timestamp"]`

This won't work for HousePredictionModel which is a regression model (LinearRegression).

### Target State

`run_evaluate()` supports both classification and regression:
- Detect model type: if `hasattr(model, 'predict_proba')` → classification path (unchanged)
- Else → regression path: compute regression metrics (rmse, mae, r2)
- Make the "drop columns" list configurable or derive from model

### Implementation

**File:** `gcp_ml_framework/utils/evaluate.py`

Add regression metric computation:

```python
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import numpy as np

def _compute_regression_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, requested: list[str]
) -> dict[str, float]:
    available = {
        "rmse": lambda: round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": lambda: round(float(mean_absolute_error(y_true, y_pred)), 4),
        "r2": lambda: round(float(r2_score(y_true, y_pred)), 4),
        "mse": lambda: round(float(mean_squared_error(y_true, y_pred)), 4),
    }
    return {m: available[m]() for m in requested if m in available}


def _compute_classification_metrics(
    y_true: np.ndarray, y_proba: np.ndarray, requested: list[str]
) -> dict[str, float]:
    # Existing classification logic moved here
    ...
```

Main function update:

```python
def run_evaluate(*, ...):
    # ... load dataset, load model (unchanged) ...

    # Separate features and target
    target_col = "price" if "price" in df.columns else "label"
    y_true = df[target_col].values
    X = df.drop(columns=[target_col], errors="ignore")

    # Drop non-feature columns
    drop_cols = [c for c in ["user_id", "feature_timestamp", "processed_at"] if c in X.columns]
    X = X.drop(columns=drop_cols, errors="ignore")

    # Detect model type and compute metrics
    if hasattr(model, "predict_proba"):
        y_proba = model.predict_proba(X)[:, 1]
        computed = _compute_classification_metrics(y_true, y_proba, metrics)
    else:
        y_pred = model.predict(X)
        # Handle models that return DataFrames (like HousePredictionModel)
        if hasattr(y_pred, "values"):
            y_pred = y_pred.values.ravel()
        computed = _compute_regression_metrics(y_true, y_pred, metrics)

    # Gate check (unchanged)
    ...
```

### Key Consideration: HousePredictionModel.predict() Returns a DataFrame

`HousePredictionModel.predict()` returns a DataFrame with columns `["price", "is_valid", "info"]`. `run_evaluate()` must handle this:
- Extract `y_pred = predictions["price"].values` or flatten with `.values.ravel()`

**Alternative:** The data scientist overrides `EvaluateModel.run()` directly instead of using `run_evaluate()`. This is simpler and more aligned with the framework's design (data scientists override `run()`).

**Decision:** Support both. Fix `run_evaluate()` for standard sklearn models. For custom models like HousePredictionModel, the pipeline step subclass overrides `run()`.

### Tests

**File:** `tests/utils/test_evaluate.py`

```python
@pytest.mark.unit
def test_run_evaluate_regression_metrics():
    """Regression model computes rmse, mae, r2."""
    ...

@pytest.mark.unit
def test_run_evaluate_classification_metrics():
    """Classification model still computes auc, f1."""
    ...

@pytest.mark.unit
def test_run_evaluate_handles_dataframe_predictions():
    """Model returning DataFrame predictions is handled correctly."""
    ...
```

---

<a id="53"></a>
## 5.3 — Add Experiment Tracking to TrainModel

### Current State

`TrainModel.execute()` creates a temp dir, calls `run()`, uploads model to GCS. No experiment tracking.

The `experiment_name` is already populated by `_build_context_params()` via `context.naming.vertex_experiment(pipeline_name)`.

### Target State

After `run()` completes successfully, `execute()` logs training parameters to Vertex AI Experiments. This is best-effort — training should not fail if experiment logging fails.

### Implementation

**File:** `gcp_ml_framework/components/ml/train.py`

Add to `execute()` after model upload:

```python
def execute(self) -> None:
    with tempfile.TemporaryDirectory(prefix="gml_train_") as work_dir:
        self._work_dir = work_dir
        self.run()

        # Upload model artifacts to GCS (existing code)
        ...

    # Experiment tracking (best-effort)
    if self.experiment_name and self.project and self.region:
        try:
            aiplatform.init(
                project=self.project,
                location=self.region,
                experiment=self.experiment_name,
            )
            run_id = f"train-{self.run_date or 'no-date'}"
            aiplatform.start_run(run=run_id, resume=True)
            # Log non-internal fields as params
            params = {
                k: str(v) for k, v in self.model_dump().items()
                if k not in _INTERNAL_FIELDS
                and k not in ("output_uri_path",)
                and v not in ("", None, [], {})
            }
            aiplatform.log_params(params)
            logger.info("Logged training params to experiment: %s", self.experiment_name)
        except Exception:
            logger.warning("Experiment tracking failed (non-fatal)", exc_info=True)
```

### Key Details

- `resume=True` on `start_run()` — if run_id already exists (retry), resume it instead of failing
- Filter empty values to keep experiment logs clean
- `_INTERNAL_FIELDS` already defined in `base.py` — reuse it
- Import `_INTERNAL_FIELDS` from base module or redefine locally (check which is cleaner)
- `aiplatform` import: already used in the project, add to train.py imports

### Tests

**File:** `tests/components/test_train.py`

```python
@pytest.mark.unit
@patch("gcp_ml_framework.components.ml.train.aiplatform")
def test_train_logs_experiment(mock_aip, tmp_path):
    """TrainModel.execute() logs params to Vertex AI Experiments."""
    step = TrainModel(
        experiment_name="test-exp",
        project="test-proj",
        region="us-east4",
        model_output_uri=str(tmp_path / "model"),
        output_uri_path=str(tmp_path / "output"),
    )
    step.run = lambda: (tmp_path / "model.pkl").write_text("fake")
    step._work_dir = str(tmp_path)
    step.execute()

    mock_aip.init.assert_called_once()
    mock_aip.start_run.assert_called_once()
    mock_aip.log_params.assert_called_once()

@pytest.mark.unit
@patch("gcp_ml_framework.components.ml.train.aiplatform")
def test_train_experiment_failure_non_fatal(mock_aip, tmp_path):
    """Experiment tracking failure doesn't prevent training."""
    mock_aip.init.side_effect = Exception("API error")
    step = TrainModel(...)
    step.execute()  # Should not raise
```

---

<a id="54"></a>
## 5.4 — Add Experiment Tracking to EvaluateModel

### Current State

`run_evaluate()` in `utils/evaluate.py` already does best-effort experiment logging:
```python
run_id = "eval-" + hashlib.md5(model_uri.encode()).hexdigest()[:8]
aiplatform.log_metrics(computed)
```

But this is disconnected from the experiment run started by TrainModel. The run_id is different.

### Target State

EvaluateModel logs metrics to the SAME experiment run started by TrainModel. Use a consistent `run_date`-based run_id across both steps.

### Implementation

**File:** `gcp_ml_framework/components/ml/evaluate.py`

Add experiment tracking in `execute()`:

```python
def execute(self) -> None:
    self.run()

    # Experiment tracking (best-effort)
    if self.experiment_name and self.project and self.region:
        try:
            aiplatform.init(
                project=self.project,
                location=self.region,
                experiment=self.experiment_name,
            )
            # Use same run_id pattern as TrainModel for continuity
            run_id = f"train-{self.run_date or 'no-date'}"
            aiplatform.start_run(run=run_id, resume=True)
            # Log metrics computed in run()
            # Read metrics from output if available
            if self.output_uri_path and Path(self.output_uri_path).exists():
                import json
                metrics = json.loads(Path(self.output_uri_path).read_text())
                aiplatform.log_metrics(metrics)
                logger.info("Logged eval metrics to experiment: %s", self.experiment_name)
        except Exception:
            logger.warning("Experiment metric logging failed (non-fatal)", exc_info=True)
```

### Key Details

- `resume=True` + same `run_id` as TrainModel means both params and metrics appear on the same experiment run
- Metrics are read from `output_uri_path` (already written by `run_evaluate()`)
- If `run_evaluate()` already logged metrics with its own run_id, we can remove that duplicate logging from `run_evaluate()` to avoid confusion

### Alternative: Remove experiment logging from run_evaluate()

Since `execute()` now handles experiment tracking, remove the experiment logging from `run_evaluate()` in `utils/evaluate.py`. This keeps experiment tracking at the component lifecycle level (execute) rather than the utility level.

**Decision:** Remove from `run_evaluate()`, keep in `execute()` only. Single responsibility.

### Tests

**File:** `tests/components/test_evaluate.py`

```python
@pytest.mark.unit
@patch("gcp_ml_framework.components.ml.evaluate.aiplatform")
def test_evaluate_logs_metrics_to_experiment(mock_aip, tmp_path):
    """EvaluateModel.execute() logs metrics to Vertex AI Experiments."""
    ...

@pytest.mark.unit
def test_evaluate_experiment_failure_non_fatal(mock_aip, tmp_path):
    """Experiment tracking failure doesn't prevent evaluation."""
    ...
```

---

<a id="55"></a>
## 5.5 — Add Monitoring Fields to DeployModel

### Current State

`DeployModel` has deployment fields only: model_uri, endpoint_name, machine_type, replicas, traffic_split.

No model monitoring capability.

### Target State

`DeployModel` has optional monitoring fields that configure Vertex AI Model Deployment Monitoring when enabled.

### Implementation

**File:** `gcp_ml_framework/components/ml/deploy.py`

Add fields:

```python
@ml_task
class DeployModel(BaseComponent):
    # ... existing fields ...

    # Monitoring (optional)
    enable_monitoring: bool = False
    monitoring_alert_email: str = ""
    monitoring_log_sample_rate: float = 0.8
    monitoring_monitor_interval: int = 3600  # seconds
    monitoring_skew_thresholds: dict[str, float] = Field(default_factory=dict)
    monitoring_drift_thresholds: dict[str, float] = Field(default_factory=dict)
```

### Update _INTERNAL_FIELDS

**File:** `gcp_ml_framework/components/base.py`

Monitoring config fields shouldn't be exposed as KFP inputs. They're deployment configuration, not per-run parameters. Add to `_INTERNAL_FIELDS`:

```python
_INTERNAL_FIELDS = frozenset({
    "component_name", "component_version", "timeout_seconds",
    "retry_count", "cache_enabled",
    # Monitoring config (deployment-time, not per-run)
    "enable_monitoring", "monitoring_alert_email",
    "monitoring_log_sample_rate", "monitoring_monitor_interval",
    "monitoring_skew_thresholds", "monitoring_drift_thresholds",
})
```

**Wait — reconsider.** Monitoring fields ARE per-pipeline configuration. A data scientist sets them in `pipeline.py`:

```python
pipeline.add(DeployModel(
    enable_monitoring=True,
    monitoring_alert_email="team@company.com",
    monitoring_skew_thresholds={"area": 0.3},
), name="Deploy")
```

These values need to flow through the compiler into the KFP container. So they should NOT be in `_INTERNAL_FIELDS`. They should be regular fields that get passed as KFP params.

**Decision:** Keep monitoring fields as regular Pydantic fields. They'll be serialized as CLI flags and passed into the container like all other fields.

### Tests

```python
@pytest.mark.unit
def test_deploy_model_monitoring_defaults():
    """Monitoring is disabled by default."""
    d = DeployModel(endpoint_name="test")
    assert d.enable_monitoring is False

@pytest.mark.unit
def test_deploy_model_monitoring_enabled():
    """Monitoring fields accepted when enabled."""
    d = DeployModel(
        endpoint_name="test",
        enable_monitoring=True,
        monitoring_alert_email="a@b.com",
        monitoring_skew_thresholds={"area": 0.3},
    )
    assert d.enable_monitoring is True
```

---

<a id="56"></a>
## 5.6 — Update run_deploy() and DeployModel for Monitoring

### Current State

`run_deploy()` deploys model to endpoint. No monitoring setup. `DeployModel.run()` calls `run_deploy()` but has no monitoring parameters to pass.

### Target State

After deployment, if monitoring is enabled, create a Model Deployment Monitoring Job. `DeployModel.run()` passes all monitoring fields through to `run_deploy()`.

### Implementation

**File:** `gcp_ml_framework/utils/vertex.py`

Update `run_deploy()` signature:

```python
def run_deploy(
    *,
    project: str,
    region: str,
    model_uri: str,
    model_display_name: str,
    endpoint_display_name: str,
    serving_container_image: str,
    machine_type: str,
    min_replica_count: int,
    max_replica_count: int,
    traffic_split: dict[str, int],
    output_uri_path: str,
    # Monitoring (new)
    enable_monitoring: bool = False,
    monitoring_alert_email: str = "",
    monitoring_log_sample_rate: float = 0.8,
    monitoring_monitor_interval: int = 3600,
    monitoring_skew_thresholds: dict[str, float] | None = None,
    monitoring_drift_thresholds: dict[str, float] | None = None,
) -> None:
```

Add monitoring setup after deployment:

```python
    # ... existing deployment code ...

    # Model monitoring (optional)
    if enable_monitoring:
        from google.cloud.aiplatform_v1.types import (
            ModelDeploymentMonitoringJob,
            ModelDeploymentMonitoringObjectiveConfig,
            ModelDeploymentMonitoringScheduleConfig,
            ModelMonitoringAlertConfig,
            ModelMonitoringObjectiveConfig,
            ThresholdConfig,
        )

        objective_config = ModelDeploymentMonitoringObjectiveConfig(
            deployed_model_id=deployed_model_id,
            objective_config=ModelMonitoringObjectiveConfig(
                training_dataset=...,  # Optional: reference training data
                training_prediction_skew_detection_config=ThresholdConfig(
                    value={k: ThresholdConfig.ThresholdValue(value=v)
                           for k, v in (monitoring_skew_thresholds or {}).items()}
                ),
                prediction_drift_detection_config=ThresholdConfig(
                    value={k: ThresholdConfig.ThresholdValue(value=v)
                           for k, v in (monitoring_drift_thresholds or {}).items()}
                ),
            ),
        )

        # Simplified approach using the high-level SDK
        monitoring_job = aiplatform.ModelDeploymentMonitoringJob.create(
            display_name=f"{endpoint_display_name}-monitoring",
            endpoint=endpoint,
            logging_sampling_strategy={"random_sample_config": {"sample_rate": monitoring_log_sample_rate}},
            schedule_config={"monitor_interval": {"seconds": monitoring_monitor_interval}},
            alert_config={"email_alert_config": {"user_emails": [monitoring_alert_email]}} if monitoring_alert_email else None,
            objective_configs=objective_config,
        )
        logger.info("Created monitoring job: %s", monitoring_job.resource_name)
```

### Important Note

The Vertex AI Model Monitoring API has evolved. The exact API depends on the `google-cloud-aiplatform` SDK version. Two approaches:

**Approach A (High-level SDK):** `aiplatform.ModelDeploymentMonitoringJob.create()` — cleaner but may not be available in all SDK versions.

**Approach B (REST/v1beta1):** Use the low-level `ModelDeploymentMonitoringServiceClient` — more verbose but universally available.

**Decision:** Use Approach A first. If SDK version doesn't support it, fall back to Approach B. Wrap in try/except with clear logging.

### Tests

```python
@pytest.mark.unit
def test_run_deploy_with_monitoring(mock_aiplatform):
    """When enable_monitoring=True, creates monitoring job."""
    run_deploy(..., enable_monitoring=True, monitoring_alert_email="a@b.com")
    mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_called_once()

@pytest.mark.unit
def test_run_deploy_without_monitoring(mock_aiplatform):
    """When enable_monitoring=False, no monitoring job created."""
    run_deploy(..., enable_monitoring=False)
    mock_aiplatform.ModelDeploymentMonitoringJob.create.assert_not_called()
```

### Update DeployModel.run() to Pass Monitoring Fields

**File:** `gcp_ml_framework/components/ml/deploy.py`

`DeployModel.run()` (or `execute()`) must pass all monitoring fields to `run_deploy()`:

```python
def run(self) -> None:
    run_deploy(
        project=self.project,
        region=self.region,
        model_uri=self.model_uri,
        model_display_name=self.model_display_name,
        endpoint_display_name=self.endpoint_display_name,
        serving_container_image=self.serving_container_image,
        machine_type=self.machine_type,
        min_replica_count=self.min_replica_count,
        max_replica_count=self.max_replica_count,
        traffic_split=self.traffic_split,
        output_uri_path=self.output_uri_path,
        # Monitoring fields (new)
        enable_monitoring=self.enable_monitoring,
        monitoring_alert_email=self.monitoring_alert_email,
        monitoring_log_sample_rate=self.monitoring_log_sample_rate,
        monitoring_monitor_interval=self.monitoring_monitor_interval,
        monitoring_skew_thresholds=self.monitoring_skew_thresholds,
        monitoring_drift_thresholds=self.monitoring_drift_thresholds,
    )
```

Without this change, `run_deploy()` receives monitoring parameters but `DeployModel` never passes them — monitoring would never trigger.

---

<a id="57"></a>
## 5.7 — Create Evaluation Step Subclass for Housing

### Current State

`run_evaluate()` assumes classification (predict_proba, threshold at 0.5). HousePredictionModel is a regression model.

### Target State

Pipeline step subclass overrides `run()` for housing-specific evaluation logic.

### Implementation

**File:** `pipelines/verification_pipeline/steps.py` (or `pipeline.py` inline)

```python
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.decorators import ml_task


@ml_task
class HouseEvaluateStep(EvaluateModel):
    """Housing-specific evaluation using regression metrics."""

    component_name: str = "evaluate_house_model"

    def run(self) -> None:
        """Override to handle regression evaluation for housing model."""
        import json
        import pickle
        import tempfile

        import numpy as np
        import pandas as pd
        from google.cloud import bigquery, storage
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        # Load evaluation dataset from BQ
        # Use dataset_uri if bridged from @task output (LocalRunner or 5.15 bridging),
        # otherwise fall back to constructing from self.dataset + known table name.
        # This ensures the step works in BOTH KFP (where bridging may not yet
        # provide the value) and LocalRunner (where it's always available).
        client = bigquery.Client(project=self.project)
        eval_table = self.dataset_uri or f"{self.project}.{self.dataset}.verification_features"
        query = f"SELECT * FROM `{eval_table}`"
        df = client.query(query).to_dataframe()

        # Separate target
        y_true = df["price"].values
        X = df.drop(columns=["price"], errors="ignore")

        # Drop non-feature columns
        X = X.drop(columns=["processed_at", "user_id", "feature_timestamp"], errors="ignore")

        # Load model from GCS
        storage_client = storage.Client(project=self.project)
        uri_parts = self.model_uri.replace("gs://", "").split("/", 1)
        bucket = storage_client.bucket(uri_parts[0])
        blob = bucket.blob(f"{uri_parts[1]}/model.pkl")
        with tempfile.NamedTemporaryFile(suffix=".pkl") as tmp:
            blob.download_to_filename(tmp.name)
            with open(tmp.name, "rb") as f:
                model = pickle.load(f)  # noqa: S301

        # Predict
        predictions = model.predict(X)
        if hasattr(predictions, "values"):
            y_pred = predictions["price"].values if "price" in predictions.columns else predictions.values.ravel()
        else:
            y_pred = np.array(predictions).ravel()

        # Compute regression metrics
        computed = {}
        for m in self.metrics:
            if m == "rmse":
                computed[m] = round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4)
            elif m == "mae":
                computed[m] = round(float(mean_absolute_error(y_true, y_pred)), 4)
            elif m == "r2":
                computed[m] = round(float(r2_score(y_true, y_pred)), 4)

        logger.info("Evaluation metrics: %s", computed)

        # Gate check
        failures = []
        for metric_name, threshold in self.gate.items():
            if metric_name in computed:
                if metric_name in ("rmse", "mae"):
                    # Lower is better
                    if computed[metric_name] > threshold:
                        failures.append(f"{metric_name}={computed[metric_name]} > {threshold}")
                else:
                    # Higher is better (r2)
                    if computed[metric_name] < threshold:
                        failures.append(f"{metric_name}={computed[metric_name]} < {threshold}")

        if failures:
            raise ValueError(f"Model failed quality gates: {', '.join(failures)}")

        # Write metrics
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(json.dumps(computed))
```

### Rationale

Overriding `run()` is the framework's intended extension point. This avoids making `run_evaluate()` overly complex with regression/classification branching. The data scientist owns the evaluation logic — this is by design.

### Tests

```python
@pytest.mark.unit
def test_house_evaluate_step_fields():
    step = HouseEvaluateStep(metrics=["rmse", "mae", "r2"], gate={"rmse": 100000})
    assert step.component_name == "evaluate_house_model"
    assert "rmse" in step.metrics
```

---

<a id="58"></a>
## 5.8 — Add serving_container_image Defaults to Compiler

### Current State

`RegisterModel` and `DeployModel` both need `serving_container_image` — the URI of a pre-built serving container that can load and serve the model.

Currently, the data scientist must set this manually. The compiler has no auto-derivation for it.

### Target State

`_build_derived_params()` in the compiler auto-populates `serving_container_image` for RegisterModel and DeployModel using the standard scikit-learn pre-built serving container from Google.

### Implementation

**File:** `gcp_ml_framework/pipeline/compiler.py`

In `_build_derived_params()`:

```python
# For RegisterModel and DeployModel — default serving container
if isinstance(component, (RegisterModel, DeployModel)):
    if not component.serving_container_image:
        derived[step_name]["serving_container_image"] = (
            "us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest"
        )
```

### Alternative

Let the pipeline author set it explicitly:
```python
pipeline.add(RegisterModel(serving_container_image="us-docker.pkg.dev/..."), name="Register")
```

**Decision:** Auto-populate a sensible default in the compiler, but let explicit values override. The sklearn serving container is appropriate for our HousePredictionModel. Data scientists with custom models override it in their pipeline definition.

### Note on Serving Container

The correct serving container URI for sklearn models on Vertex AI is:
- `us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-3:latest` (sklearn 1.3)

This may need updating based on the sklearn version used. Check `pyproject.toml` for the actual sklearn version.

### Risk: Custom Model Interface

`HousePredictionModel.predict()` returns a **DataFrame** with columns `["price", "is_valid", "info"]`, not a numpy array. The pre-built sklearn serving container calls `model.predict()` and serializes the response. This may cause issues:

- If the container expects `ndarray` → serialization error
- If the container handles DataFrames → response shape may be unexpected

**Mitigation options (in order of preference):**
1. **Verify during E2E** — Deploy and test prediction endpoint. Pre-built containers may handle DataFrames fine.
2. **Custom Prediction Routine (CPR)** — Vertex AI supports custom `predict()` wrappers. Add a `predictor.py` that wraps HousePredictionModel.
3. **Change model interface** — Make `predict()` return ndarray. This is a breaking change to `second_run/estimator.py`.

**Decision:** Verify during E2E (option 1). If it fails, implement CPR (option 2). Do NOT change the model interface without discussing with the team.

### Tests

```python
@pytest.mark.unit
def test_compiler_sets_default_serving_container():
    """RegisterModel gets default serving container if not set."""
    ...
```

---

<a id="59"></a>
## 5.9 — Wire Full training_pipeline (6 Steps)

### Current State

`pipelines/training_pipeline/pipeline.py` has 1 step: HouseTrainModelStep.

### Target State

Full 6-step pipeline:

```python
from gcp_ml_framework.components.bq import BQQuery, BQTransform
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.pipeline.pipeline import Pipeline

from .steps import HouseEvaluateStep, HouseTrainModelStep

pipeline = (
    Pipeline(name="training_pipeline", schedule="@daily")
    .add(
        BQQuery(
            sql="SELECT * FROM `{bq_dataset}.housing_data_table`",
            destination_table="training_raw",
            component_name="ingest_raw_data",
        ),
        name="Ingest Raw Data",
    )
    .add(
        BQTransform(
            sql="SELECT *, CURRENT_TIMESTAMP() AS processed_at FROM `{bq_dataset}.training_raw`",
            output_table="training_features",
            component_name="transform_features",
        ),
        name="Transform Features",
    )
    .add(
        HouseTrainModelStep(
            component_name="train_house_model",
            machine_type="n2-standard-4",
        ),
        name="Train Model",
    )
    .add(
        HouseEvaluateStep(
            metrics=["rmse", "mae", "r2"],
            gate={"rmse": 100000},
            component_name="evaluate_house_model",
            machine_type="n2-standard-4",
        ),
        name="Evaluate Model",
    )
    .add(
        RegisterModel(
            component_name="register_model",
        ),
        name="Register Model",
    )
    .add(
        DeployModel(
            endpoint_name="housing-predictor",
            machine_type="n2-standard-2",
            min_replica_count=1,
            max_replica_count=1,
            component_name="deploy_model",
        ),
        name="Deploy Model",
    )
    .build()
)
```

### Steps File

**File:** `pipelines/training_pipeline/steps.py`

The existing `HouseTrainModelStep` lives at `pipelines/training_pipeline/steps/train_house_model.py`. It already reads from a SQL file that formats with `{dataset}`. Two options:

**Option A:** Keep the SQL file approach but update `training_pipeline_features.sql` to read from the BQTransform output table:
```sql
-- pipelines/training_pipeline/sql/training_pipeline_features.sql
SELECT * FROM `{dataset}.training_features`
```

**Option B:** Simplify `HouseTrainModelStep.run()` to construct the query inline (matching `TrainVerifyModelStep`'s pattern):
```python
query = f"SELECT * FROM `{self.dataset}.training_features`"
```

**Decision:** Option A — keep the SQL file pattern (it's already established and allows complex transformations). Just update the SQL to reference the correct table.

Add `HouseEvaluateStep` alongside the existing step:

```python
# pipelines/training_pipeline/steps/evaluate_house_model.py

from gcp_ml_framework.components.ml.evaluate import EvaluateModel


class HouseEvaluateStep(EvaluateModel):
    """Housing-specific evaluation using regression metrics."""

    component_name: str = "evaluate_house_model"

    def run(self) -> None:
        # Same pattern as 5.7 but with training_features table:
        eval_table = self.dataset_uri or f"{self.project}.{self.dataset}.training_features"
        # ... (regression evaluation logic as defined in 5.7)
        ...
```

**Important:** `self.dataset` is the BQ dataset name (e.g., `mlplatform_second_run_version_`). The step constructs the full table reference by appending the known table name. This is the same pattern used by `TrainVerifyModelStep` which reads `f"{self.dataset}.verification_features"`.

### Compiler Output

SmartCompiler will produce:
- **Airflow DAG:** `ingest_raw_data >> transform_features >> run_vertex_pipeline_1`
- **KFP YAML:** 4 container steps (train → evaluate → register → deploy)

### Tests

```python
@pytest.mark.unit
def test_training_pipeline_has_six_steps():
    from pipelines.training_pipeline.pipeline import pipeline
    assert len(pipeline.steps) == 6

@pytest.mark.unit
def test_training_pipeline_step_types():
    from pipelines.training_pipeline.pipeline import pipeline
    step_types = [(s.name, s.component.task_type.value) for s in pipeline.steps]
    assert step_types == [
        ("Ingest Raw Data", "task"),
        ("Transform Features", "task"),
        ("Train Model", "ml_task"),
        ("Evaluate Model", "ml_task"),
        ("Register Model", "ml_task"),
        ("Deploy Model", "ml_task"),
    ]
```

---

<a id="510"></a>
## 5.10 — Expand verification_pipeline (6 Steps)

### Current State

3 steps: BQQuery → BQTransform → TrainVerifyModelStep

### Target State

6 steps: BQQuery → BQTransform → TrainVerifyModelStep → EvaluateVerifyStep → RegisterModel → DeployModel

### Implementation

**File:** `pipelines/verification_pipeline/pipeline.py`

```python
pipeline = (
    Pipeline(name="verification_pipeline", schedule="@daily")
    .add(
        BQQuery(
            sql="SELECT * FROM `{bq_dataset}.housing_data_table` WHERE 1=1",
            destination_table="verification_raw",
            component_name="ingest_raw",
        ),
        name="Ingest Raw Data",
    )
    .add(
        BQTransform(
            sql="SELECT *, CURRENT_TIMESTAMP() AS processed_at FROM `{bq_dataset}.verification_raw`",
            output_table="verification_features",
            component_name="transform_features",
        ),
        name="Transform Features",
    )
    .add(
        TrainVerifyModelStep(
            component_name="train_verify_model",
            machine_type="n2-standard-4",
        ),
        name="Train Model",
    )
    .add(
        EvaluateVerifyStep(
            metrics=["rmse", "mae", "r2"],
            gate={"rmse": 200000},  # Relaxed gate for verification
            component_name="evaluate_verify_model",
            machine_type="n2-standard-4",
        ),
        name="Evaluate Model",
    )
    .add(
        RegisterModel(
            component_name="register_model",
        ),
        name="Register Model",
    )
    .add(
        DeployModel(
            endpoint_name="verification-predictor",
            machine_type="n2-standard-2",
            min_replica_count=1,
            max_replica_count=1,
            enable_monitoring=True,
            monitoring_alert_email="team@example.com",
            monitoring_skew_thresholds={"area": 0.3, "bedrooms": 0.3},
            component_name="deploy_model",
        ),
        name="Deploy Model",
    )
    .build()
)
```

### Key Details

- `EvaluateVerifyStep` reuses the same pattern as `HouseEvaluateStep` (regression metrics)
- Gate threshold is relaxed (`rmse: 200000`) since verification uses a tiny dataset
- `enable_monitoring=True` demonstrates the monitoring capability
- `monitoring_skew_thresholds` set on key features to prove the feature works

### Tests

```python
@pytest.mark.unit
def test_verification_pipeline_has_six_steps():
    from pipelines.verification_pipeline.pipeline import pipeline
    assert len(pipeline.steps) == 6
```

---

<a id="511"></a>
## 5.11 — Fix LocalRunner & Compiler Cross-Step Wiring for RegisterModel

### Current State

Both `compiler.py` and `local_runner.py` track outputs:
- `TrainModel` output → `last_model_output`
- Everything else (except WriteFeatures) → `last_dataset_output`

`RegisterModel` outputs the model's resource_name (e.g., `projects/.../models/123`). This goes to `last_dataset_output`.

`DeployModel` receives `model_uri` from `last_model_output` (which is TrainModel's GCS path). Result: `run_deploy()` re-uploads the model.

### Target State

After `RegisterModel`, its output (resource_name) should update `last_model_output`. This way `DeployModel.model_uri` receives the registered model resource_name, and `run_deploy()` uses the existing model (via smart resolution from 5.1).

### Implementation

**File:** `gcp_ml_framework/pipeline/compiler.py`

In `_build_kfp_pipeline()`, update the output tracking logic:

```python
# Current:
if isinstance(component, TrainModel):
    last_model_output = task.outputs["output_uri_path"]
elif not isinstance(component, WriteFeatures):
    last_dataset_output = task.outputs["output_uri_path"]

# Updated:
if isinstance(component, (TrainModel, RegisterModel)):
    last_model_output = task.outputs["output_uri_path"]
elif not isinstance(component, WriteFeatures):
    last_dataset_output = task.outputs["output_uri_path"]
```

**File:** `gcp_ml_framework/pipeline/local_runner.py`

Same change:

```python
# Current:
if isinstance(component, TrainModel):
    last_model_output = output_value
elif not isinstance(component, WriteFeatures):
    last_dataset_output = output_value

# Updated:
if isinstance(component, (TrainModel, RegisterModel)):
    last_model_output = output_value
elif not isinstance(component, WriteFeatures):
    last_dataset_output = output_value
```

### Impact

After this change:
1. TrainModel outputs GCS path → `last_model_output` = `gs://bucket/.../model`
2. EvaluateModel reads `model_uri` from `last_model_output` (GCS path — correct for loading model.pkl)
3. RegisterModel reads `model_uri` from `last_model_output` (GCS path — correct for Model.upload)
4. RegisterModel outputs resource_name → `last_model_output` = `projects/.../models/123`
5. DeployModel reads `model_uri` from `last_model_output` (resource_name → smart resolution skips re-upload)

### Tests

```python
@pytest.mark.unit
def test_compiler_register_model_updates_last_model_output():
    """RegisterModel output goes to last_model_output, not last_dataset_output."""
    ...

@pytest.mark.unit
def test_local_runner_register_model_updates_last_model_output():
    """LocalRunner threads RegisterModel output to DeployModel.model_uri."""
    ...
```

---

<a id="512"></a>
## 5.12 — Tests

### New Test Files

| File | Tests | Purpose |
|------|-------|---------|
| `tests/utils/test_vertex.py` | 4 | Smart model resolution in run_deploy(), monitoring |
| `tests/utils/test_evaluate.py` | 3 | Regression metrics, DataFrame handling |
| `tests/components/test_train.py` | 2+ | Experiment tracking in execute() |
| `tests/components/test_evaluate.py` | 2+ | Experiment metric logging |
| `tests/components/test_deploy.py` | 2 | Monitoring fields |
| `tests/components/test_bq_query.py` | 2 | BQQuery output_uri_path writing |
| `tests/pipelines/test_training_pipeline.py` | 3+ | 6-step pipeline structure, step types |
| `tests/pipelines/test_verification_pipeline.py` | 3+ | 6-step structure, monitoring enabled |
| `tests/pipelines/test_mixed_pipeline.py` | 4+ | Mixed @task/@ml_task pattern, group boundaries |
| `tests/pipeline/test_compiler.py` | 3+ | RegisterModel wiring, bridged KFP params |
| `tests/pipeline/test_smart_compiler.py` | 5+ | @task→@ml_task bridging, output tracking across groups |
| `tests/pipeline/test_local_runner.py` | 1+ | RegisterModel wiring |

### Existing Tests to Update

- Any tests that assert pipeline step counts (3 → 6 for verification)
- Any tests that assert `last_model_output` tracking behavior
- Compiler tests that check cross-step wiring
- SmartCompiler tests that check `parameter_values` in generated DAGs

### Test Targets

- **Before Phase 5:** 147 tests, 0 failures
- **After Phase 5:** ~180+ tests, 0 failures

### Running Tests

```bash
# All unit tests
uv run -- pytest tests/ -m unit -v

# Just Phase 5 new tests
uv run -- pytest tests/utils/test_vertex.py tests/utils/test_evaluate.py tests/components/ tests/pipelines/ -m unit -v

# Ruff check
uv run -- ruff check gcp_ml_framework/ tests/ pipelines/ second_run/
```

---

<a id="513"></a>
## 5.13 — Full E2E Verification

### Local E2E (Against Real GCP Dev Resources)

```bash
# Compile both pipelines
UV_ENV_FILE=.env uv run -- gml compile --all

# Verify compiled outputs
ls compiled_pipelines/  # Should have training_pipeline.yaml and verification_pipeline.yaml
ls dags/                # Should have both DAGs

# Inspect DAGs — should have 3 tasks each (2 BQ operators + 1 RunPipelineJobOperator)
cat dags/mlplatform_second_run_*_training_pipeline.py
cat dags/mlplatform_second_run_*_verification_pipeline.py

# Build Docker images (needed for @ml_task container steps)
UV_ENV_FILE=.env uv run -- gml build training_pipeline
UV_ENV_FILE=.env uv run -- gml build verification_pipeline

# Run locally
UV_ENV_FILE=.env uv run -- gml run verification_pipeline --local
UV_ENV_FILE=.env uv run -- gml run training_pipeline --local
```

### Expected Local Run Behavior

1. **Ingest** — BQ query runs, creates `verification_raw` / `training_raw` table
2. **Transform** — BQ transform runs, creates `verification_features` / `training_features` table
3. **Train** — Downloads data from BQ, trains HousePredictionModel, uploads model.pkl to GCS
4. **Evaluate** — Downloads model from GCS, loads eval data from BQ, computes rmse/mae/r2, checks gates
5. **Register** — Uploads model to Vertex AI Model Registry
6. **Deploy** — Deploys registered model to endpoint (creates endpoint if needed)

### Cloud E2E (Full Vertex AI)

```bash
# Deploy (compile + verify images + upload DAGs + upload YAML to GCS)
UV_ENV_FILE=.env uv run -- gml deploy verification_pipeline

# Trigger via Composer
UV_ENV_FILE=.env uv run -- gml run verification_pipeline
```

### Verification Checklist

- [ ] `gml compile --all` produces valid DAGs and YAML
- [ ] DAGs have correct structure (2 BQ operators + 1 RunPipelineJobOperator)
- [ ] KFP YAML has 4 container steps (train, evaluate, register, deploy)
- [ ] `gml run verification_pipeline --local` — all 6 steps complete
- [ ] Model artifact uploaded to GCS
- [ ] Model registered in Vertex AI Model Registry
- [ ] Endpoint created/reused, model deployed
- [ ] Experiment run visible in Vertex AI Experiments UI (params + metrics)
- [ ] Monitoring job created (if enable_monitoring=True)
- [ ] `gml run training_pipeline --local` — all 6 steps complete
- [ ] All unit tests pass (170+)
- [ ] Ruff clean across entire codebase

---

## File Change Summary

### New Files (4)

| File | Purpose |
|------|---------|
| `pipelines/training_pipeline/steps/evaluate_house_model.py` | HouseEvaluateStep for training pipeline |
| `pipelines/verification_pipeline/steps/evaluate_verify_model.py` | EvaluateVerifyStep for verification pipeline |
| `pipelines/mixed_test_pipeline/pipeline.py` | Mixed @task/@ml_task scenario test pipeline |
| `tests/utils/test_vertex.py` | Tests for run_deploy() smart resolution + monitoring |

### Modified Files (16)

| File | Changes |
|------|---------|
| `gcp_ml_framework/utils/vertex.py` | Smart model resolution + monitoring in run_deploy() |
| `gcp_ml_framework/utils/evaluate.py` | Regression metrics support, remove experiment logging (moved to execute()) |
| `gcp_ml_framework/components/ml/train.py` | Experiment tracking in execute() |
| `gcp_ml_framework/components/ml/evaluate.py` | Experiment metric logging in execute() |
| `gcp_ml_framework/components/ml/deploy.py` | Add monitoring fields, update run() to pass them to run_deploy() |
| `gcp_ml_framework/components/operators/bq_query.py` | Add output_uri_path writing in execute() |
| `gcp_ml_framework/pipeline/compiler.py` | RegisterModel → last_model_output, serving_container defaults, accept bridged params |
| `gcp_ml_framework/pipeline/local_runner.py` | RegisterModel → last_model_output |
| `gcp_ml_framework/pipeline/smart_compiler.py` | @task→@ml_task data bridging: track outputs across groups, pass as parameter_values |
| `pipelines/training_pipeline/pipeline.py` | Expand to 6 steps |
| `pipelines/training_pipeline/sql/training_pipeline_features.sql` | Update to read from `{dataset}.training_features` |
| `pipelines/verification_pipeline/pipeline.py` | Expand to 6 steps |
| `tests/utils/test_evaluate.py` | Regression metric tests |
| `tests/components/test_train.py` | Experiment tracking tests |
| `tests/components/test_evaluate.py` | Experiment metric logging tests |
| `tests/components/test_deploy.py` | Monitoring field tests |

### No Changes Needed

| File | Reason |
|------|--------|
| `gcp_ml_framework/components/base.py` | _INTERNAL_FIELDS unchanged (monitoring fields flow through KFP) |
| `gcp_ml_framework/naming.py` | Already has vertex_experiment(), vertex_model_name(), vertex_endpoint_name() |
| `second_run/estimator.py` | HousePredictionModel unchanged |
| `docker/` | No Dockerfile changes needed |
| `terraform/` | No infra changes (endpoints are created dynamically) |

---

## Implementation Order (Critical Path)

```
Phase 5A: Foundation (utility fixes)
  5.1  Fix run_deploy() smart resolution     ← Foundation for Deploy step
  5.2  Fix run_evaluate() regression          ← Foundation for Evaluate step
  5.14 BQQuery output tracking               ← Foundation for bridging
    ↓
Phase 5B: Framework features (parallelizable)
  5.3  Experiment tracking in TrainModel      ← Independent
  5.4  Experiment tracking in EvaluateModel   ← Independent
  5.5  Monitoring fields on DeployModel       ← Independent
  5.6  Update run_deploy() + DeployModel      ← Depends on 5.5
  5.8  serving_container_image defaults       ← Independent
    ↓
Phase 5C: Cross-step wiring
  5.11 Fix wiring (Register→Deploy)           ← Must be before pipeline wiring
  5.15 @task→@ml_task data bridging           ← Depends on 5.14; must be before pipelines
    ↓
Phase 5D: Pipeline wiring
  5.7  Create HouseEvaluateStep subclass      ← Depends on 5.2
  5.9  Wire training_pipeline (6 steps)       ← Depends on 5.7, 5.8, 5.11, 5.15
  5.10 Expand verification_pipeline           ← Depends on 5.7, 5.8, 5.11, 5.15
    ↓
Phase 5E: Verification
  5.12 Tests                                  ← After all implementation
  5.13 E2E verification (6-step)              ← Verify pipelines work
  5.16 Mixed execution scenario test          ← Verify bridging edge cases
  5.17 Final E2E (mixed + bridging)           ← Final
```

**Parallelizable:** 5.3, 5.4, 5.5, 5.8, 5.14 are all independent and can be done simultaneously.

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| HousePredictionModel.predict() returns DataFrame — breaks run_evaluate() | HouseEvaluateStep overrides run() entirely, bypassing run_evaluate() |
| HousePredictionModel.predict() returns DataFrame — breaks pre-built serving container | Verify during E2E; fall back to Custom Prediction Routine (CPR) if needed |
| RegisterModel→DeployModel wiring breaks existing tests | Update existing compiler/LocalRunner tests to expect new behavior |
| Monitoring API version mismatch | Wrap monitoring setup in try/except, log warning on failure |
| serving_container_image wrong sklearn version | Check pyproject.toml, use matching pre-built container |
| Experiment tracking fails on local (no Vertex AI Experiments locally) | Best-effort with try/except, log warning |
| Gate thresholds too strict for verification pipeline | Use relaxed thresholds (rmse: 200000) for verification |
| EvaluateModel.dataset_uri empty in KFP (no upstream @task in KFP pipeline) | Step subclass falls back to `self.dataset + ".table_name"`; 5.15 bridging provides it via parameter_values |
| @task→@ml_task bridging adds complexity to SmartCompiler | Changes are isolated to output tracking + parameter_values generation; existing DAG structure unchanged |
| DeployModel.run() doesn't pass monitoring fields | Explicitly addressed in 5.6 — must update run() to pass all self.monitoring_* fields |
| training_pipeline_features.sql reads wrong table after pipeline expansion | Must update SQL to read from `{dataset}.training_features` (BQTransform output) |

---

<a id="514"></a>
## 5.14 — BQQuery Output Tracking

### Current State

`BQQuery.execute()` runs a BQ query and writes to a destination table, but does NOT write to `output_uri_path`. In contrast, `BQTransform.execute()` writes the full table path (`{project}.{dataset}.{output_table}`) to `output_uri_path`.

This inconsistency means:
- LocalRunner: `last_dataset_output` is NOT set after BQQuery (only after BQTransform)
- SmartCompiler: cannot bridge BQQuery output to @ml_task group

### Target State

`BQQuery.execute()` writes the destination table path to `output_uri_path`, consistent with BQTransform.

### Implementation

**File:** `gcp_ml_framework/components/operators/bq_query.py`

Add to `execute()` after `job.result()`:

```python
def execute(self) -> None:
    # ... existing query execution code ...
    job = client.query(sql, job_config=job_config)
    job.result()  # block until done

    # Write output reference (consistent with BQTransform)
    if self.output_uri_path and self.destination_table:
        dest = f"{self.project}.{self.dataset}.{self.destination_table}"
        Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.output_uri_path).write_text(dest)
        logger.info("Wrote output reference: %s", dest)
```

### Tests

```python
@pytest.mark.unit
def test_bq_query_writes_output_uri(mock_bq_client, tmp_path):
    """BQQuery.execute() writes destination table path to output_uri_path."""
    output_path = str(tmp_path / "output")
    step = BQQuery(
        sql="SELECT 1",
        destination_table="test_table",
        project="test-proj",
        dataset="test_ds",
        output_uri_path=output_path,
    )
    step.execute()
    assert Path(output_path).read_text() == "test-proj.test_ds.test_table"

@pytest.mark.unit
def test_bq_query_no_output_without_destination(mock_bq_client, tmp_path):
    """BQQuery without destination_table does not write output."""
    output_path = str(tmp_path / "output")
    step = BQQuery(sql="SELECT 1", output_uri_path=output_path)
    step.execute()
    assert not Path(output_path).exists()
```

---

<a id="515"></a>
## 5.15 — @task → @ml_task Data Bridging in SmartCompiler

### Current State

The SmartCompiler groups consecutive same-type steps:
- @task group → native Airflow operators
- @ml_task group → RunPipelineJobOperator launching KFP pipeline

The RunPipelineJobOperator currently passes only `{"run_date": "{{ ds }}"}` as `parameter_values`. No data flows from @task outputs to @ml_task inputs.

From `discussion.md`: "From @task to @ml_task: The Airflow DAG passes the BQ table reference as a parameter to the Vertex AI pipeline." This is documented but not implemented.

### Target State

SmartCompiler bridges data between execution contexts:
1. Tracks `last_dataset_output` and `last_model_output` across ALL step groups
2. At @task→@ml_task boundary, passes tracked outputs as `parameter_values` in RunPipelineJobOperator
3. KFP pipeline definition accepts bridged values as input parameters
4. At @ml_task→@task boundary, next Airflow operator can read KFP output via XCom

### Implementation

**File:** `gcp_ml_framework/pipeline/smart_compiler.py`

The SmartCompiler needs three changes:

**Change 1: Track outputs across groups**

Currently, the SmartCompiler processes each group independently. It needs to maintain output tracking across group boundaries.

```python
def compile(self, pipeline_def, context):
    groups = self._group_steps(pipeline_def.steps)
    last_dataset_output = None
    last_model_output = None

    for group in groups:
        if group.task_type == TaskType.TASK:
            # Render Airflow operators
            for step in group.steps:
                operator_code = step.component.render_operator(...)
                # Track deterministic outputs from @task steps
                output_ref = self._compute_task_output(step, context)
                if output_ref:
                    last_dataset_output = output_ref
        elif group.task_type == TaskType.ML_TASK:
            # Compile KFP pipeline — pass bridged values
            bridged_params = {"run_date": "{{ ds }}"}
            if last_dataset_output:
                bridged_params["dataset_uri"] = last_dataset_output
            if last_model_output:
                bridged_params["model_uri"] = last_model_output

            # Generate RunPipelineJobOperator with bridged parameter_values
            ...
```

**Change 2: Compute deterministic @task output references**

@task components (BQQuery, BQTransform) produce deterministic outputs known at compile time:

```python
def _compute_task_output(self, step, context):
    """Compute the output reference for a @task step (deterministic at compile time)."""
    component = step.component
    if hasattr(component, "destination_table") and component.destination_table:
        return f"{context.gcp_project}.{context.bq_dataset}.{component.destination_table}"
    if hasattr(component, "output_table") and component.output_table:
        return f"{context.gcp_project}.{context.bq_dataset}.{component.output_table}"
    return None
```

**Change 3: KFP pipeline accepts bridged parameters**

The PipelineCompiler's `_build_kfp_pipeline()` already accepts parameters via the `@dsl.pipeline` decorator. Bridged values need to be added as pipeline-level inputs that flow to the first matching step.

In `compiler.py`, the `_build_kfp_pipeline()` function signature already takes params. Add bridged params as `dsl.Input[str]` parameters to the KFP pipeline function:

```python
@dsl.pipeline(name=pipeline_name, pipeline_root=pipeline_root)
def pipeline_fn(
    run_date: str = "",
    dataset_uri: str = "",  # Bridged from @task group
    model_uri: str = "",    # Bridged from @task group (if applicable)
):
    # First step with matching field gets the bridged value
    ...
```

The existing cross-step wiring logic already injects `dataset_uri` and `model_uri` into steps that have these fields. The bridged values become the INITIAL values for `last_dataset_output` and `last_model_output` within the KFP pipeline:

```python
# Initialize with bridged values (from @task group)
last_dataset_output = dataset_uri if dataset_uri else None
last_model_output = model_uri if model_uri else None
```

### @ml_task → @task Bridging

RunPipelineJobOperator captures KFP pipeline outputs. The next Airflow operator reads via XCom:

```python
# In generated DAG:
run_vertex_pipeline_1 = RunPipelineJobOperator(...)

# Next @task operator can reference:
next_task = BigQueryInsertJobOperator(
    ...,
    # KFP pipeline output available via XCom (Airflow 2.x+)
)
next_task.set_upstream(run_vertex_pipeline_1)
```

For Phase 5, the primary direction is @task→@ml_task. The @ml_task→@task direction is validated by the mixed execution test (5.16) and may be implemented with XCom if a concrete use case requires it.

### Tests

```python
@pytest.mark.unit
def test_smart_compiler_bridges_dataset_uri():
    """BQTransform output flows as parameter_values to RunPipelineJobOperator."""
    pipeline = (
        Pipeline(name="test")
        .add(BQTransform(output_table="features"), name="Transform")
        .add(TrainModel(), name="Train")
        .build()
    )
    dag_code = smart_compiler.compile(pipeline, context)
    assert 'dataset_uri' in dag_code  # parameter_values includes bridged value

@pytest.mark.unit
def test_smart_compiler_kfp_accepts_bridged_params():
    """KFP pipeline function accepts dataset_uri as input parameter."""
    ...

@pytest.mark.unit
def test_smart_compiler_no_bridge_without_task_output():
    """When @task steps have no output, no bridging occurs."""
    ...

@pytest.mark.unit
def test_compute_task_output_bq_query():
    """BQQuery with destination_table produces deterministic output reference."""
    ...

@pytest.mark.unit
def test_compute_task_output_bq_transform():
    """BQTransform with output_table produces deterministic output reference."""
    ...
```

---

<a id="516"></a>
## 5.16 — Mixed Execution Scenario Test

### Current State

All pipelines follow `@task, @task, @ml_task, @ml_task, ...` pattern. The SmartCompiler's edge case (from `discussion.md`): "@ml_task, @task, @ml_task = two separate Vertex AI pipelines with an Airflow task between them" is untested.

### Target State

A test pipeline validates the mixed pattern: `@task → @ml_task → @task → @ml_task`, producing two separate KFP pipelines with Airflow tasks between them.

### Implementation

**File:** `pipelines/mixed_test_pipeline/pipeline.py`

```python
"""Test-only pipeline validating mixed @task/@ml_task execution patterns.

This pipeline is NOT deployed — it exists to verify the SmartCompiler handles
group boundaries and data bridging correctly.
"""
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.register import RegisterModel

pipeline = (
    Pipeline(name="mixed_test_pipeline", schedule=None)
    .add(
        BQQuery(
            sql="SELECT * FROM `{bq_dataset}.housing_data_table` LIMIT 100",
            destination_table="mixed_raw",
            component_name="ingest",
        ),
        name="Ingest",
    )
    .add(
        TrainModel(
            component_name="train_first",
            machine_type="n2-standard-4",
        ),
        name="Train First",  # @ml_task group 1
    )
    .add(
        BQTransform(
            sql="SELECT *, CURRENT_TIMESTAMP() AS scored_at FROM `{bq_dataset}.mixed_raw`",
            output_table="mixed_scored",
            component_name="post_process",
        ),
        name="Post Process",  # @task (breaks @ml_task group)
    )
    .add(
        RegisterModel(
            component_name="register",
        ),
        name="Register",  # @ml_task group 2
    )
    .build()
)
```

### Expected SmartCompiler Output

```
Group 1: [@task]       → 1 Airflow BQ operator (Ingest)
Group 2: [@ml_task]    → RunPipelineJobOperator1 (Train First) ← bridges dataset_uri from Group 1
Group 3: [@task]       → 1 Airflow BQ operator (Post Process) ← needs model_uri from Group 2 via XCom
Group 4: [@ml_task]    → RunPipelineJobOperator2 (Register)   ← bridges model_uri from Group 2
```

Airflow DAG: `ingest >> run_vertex_pipeline_1 >> post_process >> run_vertex_pipeline_2`

### Tests

```python
@pytest.mark.unit
def test_mixed_pipeline_has_four_steps():
    from pipelines.mixed_test_pipeline.pipeline import pipeline
    assert len(pipeline.steps) == 4

@pytest.mark.unit
def test_mixed_pipeline_step_types():
    from pipelines.mixed_test_pipeline.pipeline import pipeline
    types = [s.component._task_type.value for s in pipeline.steps]
    assert types == ["task", "ml_task", "task", "ml_task"]

@pytest.mark.unit
def test_mixed_pipeline_compiles_to_four_airflow_tasks():
    """SmartCompiler produces 4 Airflow tasks: BQ op → KFP1 → BQ op → KFP2."""
    dag_code = smart_compiler.compile(mixed_pipeline, context)
    assert "run_vertex_pipeline_1" in dag_code
    assert "run_vertex_pipeline_2" in dag_code
    assert "ingest" in dag_code
    assert "post_process" in dag_code

@pytest.mark.unit
def test_mixed_pipeline_bridges_data_at_boundaries():
    """Each RunPipelineJobOperator receives bridged parameter_values."""
    dag_code = smart_compiler.compile(mixed_pipeline, context)
    # First KFP pipeline gets dataset_uri from BQQuery
    # Second KFP pipeline gets model_uri from first KFP pipeline (via XCom)
    ...
```

### Key Details

- This pipeline is **test-only** — `schedule=None`, not deployed to Composer
- It validates the hardest SmartCompiler edge case: two separate KFP pipelines in one DAG
- The `TrainModel` step here would need a `run()` override to be functional, but for compilation testing, the default is sufficient

---

<a id="517"></a>
## 5.17 — Full E2E Verification (Mixed + Bridging)

### Verification Checklist

- [ ] `gml compile --all` produces valid DAGs and YAML for all pipelines (including mixed_test_pipeline)
- [ ] mixed_test_pipeline DAG has 4 Airflow tasks (BQ → KFP1 → BQ → KFP2)
- [ ] Each RunPipelineJobOperator has bridged `parameter_values` with outputs from preceding @task group
- [ ] KFP YAML accepts bridged values as pipeline-level input parameters
- [ ] 6-step pipeline DAGs include `dataset_uri` in parameter_values for RunPipelineJobOperator
- [ ] `gml run verification_pipeline --local` — EvaluateModel receives `dataset_uri` (from BQTransform in LocalRunner)
- [ ] `gml run training_pipeline --local` — same
- [ ] All unit tests pass (target: 180+)
- [ ] Ruff clean across entire codebase

### Running Tests

```bash
# All unit tests
uv run -- pytest tests/ -m unit -v

# Ruff check
uv run -- ruff check gcp_ml_framework/ tests/ pipelines/ second_run/

# Compile all pipelines
UV_ENV_FILE=.env uv run -- gml compile --all

# Inspect DAGs for bridged parameter_values
grep -A5 "parameter_values" dags/mlplatform_second_run_*_verification_pipeline.py
grep -A5 "parameter_values" dags/mlplatform_second_run_*_mixed_test_pipeline.py
```
