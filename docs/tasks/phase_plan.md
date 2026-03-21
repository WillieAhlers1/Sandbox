# Phase 4.5: Detailed Implementation Plan

**Goal:** Fix all structural gaps in the unified architecture so Phase 5 builds on a solid foundation.

**Starting state:** 147 passing unit tests, ruff clean, training_pipeline E2E verified on GCP.

**TDD discipline:** For every sub-task: write tests → watch them fail → implement → watch them pass → ruff check.

**Package manager:** `uv` exclusively. Never use pip or python directly.

**Test runner:** `uv run -- pytest tests/ -m unit -v`

**Linter:** `uv run -- ruff check gcp_ml_framework/ tests/`

---

## Table of Contents

1. [4.5.1 — Add @ml_task Decorators](#451)
2. [4.5.2 — Fix execute()→run() Lifecycle](#452)
3. [4.5.3 — Fix render_operator() Across All @task Components](#453)
4. [4.5.4 — Fix SmartCompiler No-Op Fallback](#454)
5. [4.5.5 — Remove Redundant & Broken Components](#455)
6. [4.5.6 — Collapse Pipeline API (REQS 11.0)](#456)
7. [4.5.7 — Create verification_pipeline](#457)
8. [4.5.8 — Tests for verification_pipeline](#458)
9. [4.5.9 — Fix CLI Bugs](#459)
10. [4.5.10 — Full Verification](#4510)

---

<a id="451"></a>
## 4.5.1 — Add @ml_task Decorators to ML Components

### Current State

The 4 ML components (`TrainModel`, `EvaluateModel`, `RegisterModel`, `DeployModel`) rely on `BaseComponent._task_type = TaskType.ML_TASK` (the default on `base.py:50`). This works by accident but contradicts the decorator architecture where `@task` and `@ml_task` are the explicit routing decisions.

### Target State

All 4 ML components have explicit `@ml_task` decorators, matching how all `@task` components already have explicit `@task` decorators.

### Step 1: Update Tests

**File:** `tests/components/test_decorators.py`

The existing `test_ml_components_are_ml_task` test (lines 91-101) currently passes because the components inherit `ML_TASK` from `BaseComponent`. After adding `@ml_task`, the test still passes — but we need to verify the decorator is explicitly applied, not just inherited.

Add a new test to `TestDefaultTaskTypes`:

```python
def test_ml_components_have_explicit_decorator(self):
    """ML components should have @ml_task applied directly, not inherited."""
    from gcp_ml_framework.components.ml.deploy import DeployModel
    from gcp_ml_framework.components.ml.evaluate import EvaluateModel
    from gcp_ml_framework.components.ml.register import RegisterModel
    from gcp_ml_framework.components.ml.train import TrainModel

    # After adding @ml_task, the _task_type is set by the decorator on the class
    # itself, not inherited from BaseComponent. We verify by checking that
    # the class's own __dict__ has _task_type (set by decorator), not just
    # inherited from the base.
    for cls in [TrainModel, EvaluateModel, RegisterModel, DeployModel]:
        assert "_task_type" in cls.__dict__, (
            f"{cls.__name__} should have @ml_task decorator (own _task_type), "
            f"not just inherit from BaseComponent"
        )
```

### Step 2: Watch Test Fail

```bash
uv run -- pytest tests/components/test_decorators.py::TestDefaultTaskTypes::test_ml_components_have_explicit_decorator -v
```

Expected: FAIL — `_task_type` is inherited from `BaseComponent`, not set by decorator on the class itself.

### Step 3: Implement

**File 1:** `gcp_ml_framework/components/ml/train.py`

Current (line 1-12):
```python
"""TrainModel — train a model directly inside the pipeline container."""

import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, PrivateAttr

from gcp_ml_framework.components.base import BaseComponent


class TrainModel(BaseComponent):
```

Change to:
```python
"""TrainModel — train a model directly inside the pipeline container."""

import os
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, PrivateAttr

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class TrainModel(BaseComponent):
```

**File 2:** `gcp_ml_framework/components/ml/evaluate.py`

Current (line 1-8):
```python
"""EvaluateModel — evaluate a trained model and apply metric gates."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent


class EvaluateModel(BaseComponent):
```

Change to:
```python
"""EvaluateModel — evaluate a trained model and apply metric gates."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class EvaluateModel(BaseComponent):
```

**File 3:** `gcp_ml_framework/components/ml/register.py`

Current (line 1-10):
```python
"""RegisterModel — upload a model to the Vertex AI Model Registry."""

from pathlib import Path

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent


class RegisterModel(BaseComponent):
```

Change to:
```python
"""RegisterModel — upload a model to the Vertex AI Model Registry."""

from pathlib import Path

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class RegisterModel(BaseComponent):
```

**File 4:** `gcp_ml_framework/components/ml/deploy.py`

Current (line 1-8):
```python
"""DeployModel — upload a model to Vertex AI Model Registry and deploy to an Endpoint."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent


class DeployModel(BaseComponent):
```

Change to:
```python
"""DeployModel — upload a model to Vertex AI Model Registry and deploy to an Endpoint."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import ml_task


@ml_task
class DeployModel(BaseComponent):
```

### Step 4: Verify

```bash
uv run -- pytest tests/components/test_decorators.py -v
uv run -- ruff check gcp_ml_framework/components/ml/
```

Expected: All tests pass, ruff clean.

---

<a id="452"></a>
## 4.5.2 — Fix execute()→run() Lifecycle on ML Components

### Current State

Only `TrainModel` follows the `execute()→run()` lifecycle. The other 3 ML components override `execute()` directly and never call `run()`. A data scientist who subclasses `EvaluateModel` and overrides `run()` gets `NotImplementedError` because `execute()` goes straight to a utility function.

- `TrainModel.execute()` → calls `self.run()` ✅
- `EvaluateModel.execute()` → calls `run_evaluate()` directly, never calls `self.run()` ❌
- `RegisterModel.execute()` → calls `aiplatform.Model.upload()` directly, never calls `self.run()` ❌
- `DeployModel.execute()` → calls `run_deploy()` directly, never calls `self.run()` ❌

### Target State

All ML components follow: `execute()` is the lifecycle wrapper that calls `self.run()`. Data scientists override `run()` for custom logic. Default `run()` does what `execute()` used to do.

### Step 1: Write Tests

**File:** `tests/components/test_evaluate.py` — Add new test class after existing tests:

```python
class TestEvaluateModelLifecycle:
    """Verify execute()→run() lifecycle."""

    @patch("gcp_ml_framework.utils.evaluate.run_evaluate")
    def test_execute_calls_run(self, mock_run_evaluate: MagicMock):
        """execute() should delegate to run(), not call utility directly."""
        em = EvaluateModel(
            project="test-project",
            region="us-central1",
        )
        with patch.object(em, "run") as mock_run:
            em.execute()
            mock_run.assert_called_once()

    @patch("gcp_ml_framework.utils.evaluate.run_evaluate")
    def test_subclass_run_override(self, mock_run_evaluate: MagicMock):
        """Data scientist subclass overriding run() should have custom code execute."""
        class CustomEval(EvaluateModel):
            def run(self) -> None:
                self._custom_called = True

        ce = CustomEval(project="test-project", region="us-central1")
        ce.execute()
        assert ce._custom_called is True
        # run_evaluate should NOT be called — custom run() replaced it
        mock_run_evaluate.assert_not_called()
```

**File:** `tests/components/test_register.py` — Add new test class after existing tests:

```python
class TestRegisterModelLifecycle:
    """Verify execute()→run() lifecycle."""

    def test_execute_calls_run(self, mock_aiplatform: MagicMock):
        """execute() should delegate to run()."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        rm = RegisterModel(project="test-project", region="us-central1")
        with patch.object(rm, "run", return_value="projects/123/locations/us/models/456") as mock_run:
            rm.execute()
            mock_run.assert_called_once()

    def test_execute_writes_run_return_value(self, mock_aiplatform: MagicMock, tmp_path: Path):
        """execute() writes the return value of run() to output_uri_path."""
        mock_model = MagicMock()
        mock_model.resource_name = "projects/123/locations/us/models/456"
        mock_aiplatform.Model.upload.return_value = mock_model

        output_file = tmp_path / "output" / "uri"
        rm = RegisterModel(
            project="test-project",
            region="us-central1",
            model_uri="gs://bucket/model",
            model_display_name="test-model",
            output_uri_path=str(output_file),
        )
        rm.execute()
        assert output_file.exists()
        assert output_file.read_text() == "projects/123/locations/us/models/456"
```

Add `from unittest.mock import patch` to existing imports at top of file.

**File:** `tests/components/test_deploy.py` — Add new test class after existing tests:

```python
class TestDeployModelLifecycle:
    """Verify execute()→run() lifecycle."""

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_execute_calls_run(self, mock_run_deploy: MagicMock):
        """execute() should delegate to run()."""
        dm = DeployModel(endpoint_name="test-ep", project="test-project", region="us-central1")
        with patch.object(dm, "run") as mock_run:
            dm.execute()
            mock_run.assert_called_once()

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_subclass_run_override(self, mock_run_deploy: MagicMock):
        """Data scientist subclass overriding run() should have custom code execute."""
        class CustomDeploy(DeployModel):
            def run(self) -> None:
                self._custom_called = True

        cd = CustomDeploy(endpoint_name="test-ep", project="test-project", region="us-central1")
        cd.execute()
        assert cd._custom_called is True
        mock_run_deploy.assert_not_called()
```

Add `from unittest.mock import patch` to existing imports at top of file (if not already present).

### Step 2: Watch Tests Fail

```bash
uv run -- pytest tests/components/test_evaluate.py::TestEvaluateModelLifecycle -v
uv run -- pytest tests/components/test_register.py::TestRegisterModelLifecycle -v
uv run -- pytest tests/components/test_deploy.py::TestDeployModelLifecycle -v
```

Expected: FAIL — `execute()` currently bypasses `run()`.

### Step 3: Implement

**File:** `gcp_ml_framework/components/ml/evaluate.py`

Replace the `execute` method (lines 32-45) with:

```python
    def execute(self) -> None:
        """Container lifecycle: call run()."""
        self.run()

    def run(self) -> None:
        """Evaluate model against dataset. Override for custom evaluation logic."""
        from gcp_ml_framework.utils.evaluate import run_evaluate

        run_evaluate(
            project=self.project,
            region=self.region,
            model_uri=self.model_uri,
            eval_dataset_uri=self.dataset_uri,
            metrics=self.metrics,
            gate=self.gate,
            experiment_name=self.experiment_name,
            output_uri_path=self.output_uri_path,
        )
```

**File:** `gcp_ml_framework/components/ml/register.py`

Replace the `execute` method (lines 30-43) with:

```python
    def execute(self) -> None:
        """Container lifecycle: call run(), write output URI."""
        resource_name = self.run()
        if self.output_uri_path:
            Path(self.output_uri_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.output_uri_path).write_text(resource_name)

    def run(self) -> str:
        """Register model in Vertex AI Model Registry. Override for custom registration.

        Returns:
            The registered model's resource name.
        """
        from google.cloud import aiplatform

        aiplatform.init(project=self.project, location=self.region)
        model = aiplatform.Model.upload(
            display_name=self.model_display_name,
            artifact_uri=self.model_uri,
            serving_container_image_uri=self.serving_container_image,
            labels=self.labels,
            description=self.description,
        )
        return model.resource_name
```

**File:** `gcp_ml_framework/components/ml/deploy.py`

Replace the `execute` method (lines 36-52) with:

```python
    def execute(self) -> None:
        """Container lifecycle: call run()."""
        self.run()

    def run(self) -> None:
        """Deploy model to Vertex AI Endpoint. Override for custom deployment logic."""
        from gcp_ml_framework.utils.vertex import run_deploy

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
        )
```

### Step 4: Update Existing Tests

The existing `test_evaluate_model_execute_delegates` test (test_evaluate.py:49-72) tests that `execute()` calls `run_evaluate()`. After the refactor, `execute()` calls `run()` which calls `run_evaluate()`. The mock on `run_evaluate` should still work because `run()` imports it lazily.

Similarly for `test_deploy_model_execute_delegates` (test_deploy.py:57-87) and `test_register_model_execute_calls_upload` (test_register.py:72-96).

These existing tests should STILL PASS without modification because the mock targets the utility function that `run()` now calls.

### Step 5: Verify

```bash
uv run -- pytest tests/components/ -v
uv run -- ruff check gcp_ml_framework/components/ml/
```

---

<a id="453"></a>
## 4.5.3 — Fix render_operator() Across All @task Components

### 3a. Add render_operator() to BQTransform

#### Current State

`BQTransform` (file: `gcp_ml_framework/components/transformation/bq_transform.py`) is a `@task` component that runs SQL transformations. It has no `render_operator()` method. When SmartCompiler encounters it in a compiled pipeline, it falls through to the `lambda: None` fallback (which we'll fix to raise `NotImplementedError` in 4.5.4).

#### Target State

`BQTransform.render_operator()` returns `BigQueryInsertJobOperator` code, matching the pattern used by `BQQuery.render_operator()`.

#### Step 1: Write Tests

**Create file:** `tests/components/test_bq_transform.py`

```python
"""Unit tests for BQTransform (gcp_ml_framework.components.transformation.bq_transform)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestBQTransformBasics:
    def test_is_task_type(self):
        assert BQTransform._task_type == TaskType.TASK

    def test_instantiation(self):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        assert bt.output_table == "features"
        assert bt.component_name == "bq_transform"

    def test_requires_sql_source(self):
        with pytest.raises(ValueError, match="sql_file or sql"):
            BQTransform(output_table="features")


class TestBQTransformRenderOperator:
    def test_has_render_operator(self):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        assert hasattr(bt, "render_operator")
        assert callable(bt.render_operator)

    def test_returns_bq_operator(self, mock_context):
        bt = BQTransform(output_table="features", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context)
        assert "BigQueryInsertJobOperator" in code
        assert any("BigQueryInsertJobOperator" in imp for imp in imports)

    def test_resolves_templates(self, mock_context):
        bt = BQTransform(
            output_table="features",
            sql="SELECT * FROM `{bq_dataset}.raw_data`",
        )
        code, imports = bt.render_operator(mock_context)
        assert mock_context.bq_dataset in code
        assert "{bq_dataset}" not in code

    def test_includes_destination(self, mock_context):
        bt = BQTransform(output_table="my_table", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context)
        assert "my_table" in code
        assert "destinationTable" in code

    def test_accepts_pipeline_dir_kwarg(self, mock_context):
        """render_operator() must accept pipeline_dir kwarg (SmartCompiler passes it)."""
        bt = BQTransform(output_table="features", sql="SELECT 1")
        code, imports = bt.render_operator(mock_context, pipeline_dir=None)
        assert "BigQueryInsertJobOperator" in code

    def test_run_date_becomes_jinja(self, mock_context):
        bt = BQTransform(
            output_table="features",
            sql="SELECT * WHERE date = '{run_date}'",
        )
        code, imports = bt.render_operator(mock_context)
        assert "{{ ds }}" in code
        assert "{run_date}" not in code
```

#### Step 2: Watch Tests Fail

```bash
uv run -- pytest tests/components/test_bq_transform.py -v
```

Expected: `TestBQTransformRenderOperator` tests fail — `AttributeError: 'BQTransform' object has no attribute 'render_operator'`.

#### Step 3: Implement

**File:** `gcp_ml_framework/components/transformation/bq_transform.py`

Add imports at top (after existing imports, before `@task`):

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path as PathType

    from gcp_ml_framework.context import MLContext
```

Note: `Path` is already imported from `pathlib` at line 3, so use `PathType` alias in TYPE_CHECKING to avoid collision. Actually, simpler approach: since `Path` is already imported, just add the TYPE_CHECKING block for `MLContext`:

Current imports (lines 1-8):
```python
"""BQTransform — run a SQL transformation in BigQuery and write to a BQ table."""

from pathlib import Path

from pydantic import model_validator

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task
```

Change to:
```python
"""BQTransform — run a SQL transformation in BigQuery and write to a BQ table."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import model_validator

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
```

Add the `render_operator()` method after `execute()` (after line 68):

```python
    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation."""
        from gcp_ml_framework.components.operators.bq_query import _resolve_templates

        imports = {
            "from airflow.providers.google.cloud.operators.bigquery"
            " import BigQueryInsertJobOperator",
        }

        sql = self._get_sql()
        resolved_sql = _resolve_templates(sql, context)
        escaped_sql = resolved_sql.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")

        dest = {
            "projectId": context.gcp_project,
            "datasetId": context.bq_dataset,
            "tableId": self.output_table,
        }

        code = f"""BigQueryInsertJobOperator(
        task_id="{{{{ task_id }}}}",
        configuration={{"query": {{
            "query": '''{escaped_sql}''',
            "useLegacySql": False,
            "destinationTable": {dest!r},
            "writeDisposition": "{self.write_disposition}",
            "createDisposition": "CREATE_IF_NEEDED",
        }}}},
        gcp_conn_id="google_cloud_default",
    )"""

        return code, imports
```

#### Step 4: Verify

```bash
uv run -- pytest tests/components/test_bq_transform.py -v
uv run -- ruff check gcp_ml_framework/components/transformation/bq_transform.py
```

---

### 3b. Fix Email.render_operator() Signature

#### Current State

`Email.render_operator()` (file: `gcp_ml_framework/components/operators/email.py`, line 60) has signature:
```python
def render_operator(self, context: MLContext) -> tuple[str, set[str]]:
```

SmartCompiler calls (line 318):
```python
component.render_operator(context, pipeline_dir=pipeline_dir)
```

This will crash at runtime with `TypeError: render_operator() got an unexpected keyword argument 'pipeline_dir'`.

#### Step 1: Write Test

**File:** `tests/components/test_email.py` — Add new test class:

```python
class TestEmailRenderOperator:
    def test_render_operator_accepts_pipeline_dir(self, mock_context):
        """render_operator() must accept pipeline_dir kwarg (SmartCompiler passes it)."""
        email = Email(to=["a@b.com"], subject="Test")
        # This should NOT raise TypeError
        code, imports = email.render_operator(mock_context, pipeline_dir=None)
        assert "EmailOperator" in code

    def test_render_operator_returns_email_operator(self, mock_context):
        email = Email(to=["a@b.com"], subject="Test", body="Hello")
        code, imports = email.render_operator(mock_context)
        assert "EmailOperator" in code
        assert any("EmailOperator" in imp for imp in imports)
```

#### Step 2: Watch Test Fail

```bash
uv run -- pytest tests/components/test_email.py::TestEmailRenderOperator::test_render_operator_accepts_pipeline_dir -v
```

Expected: FAIL — `TypeError: Email.render_operator() got an unexpected keyword argument 'pipeline_dir'`.

#### Step 3: Implement

**File:** `gcp_ml_framework/components/operators/email.py`

Change line 60 from:
```python
    def render_operator(self, context: MLContext) -> tuple[str, set[str]]:
```

To:
```python
    def render_operator(self, context: MLContext, pipeline_dir: Path | None = None) -> tuple[str, set[str]]:
```

Also add `Path` import. Current TYPE_CHECKING block (lines 17-18):
```python
if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
```

Change to:
```python
if TYPE_CHECKING:
    from pathlib import Path

    from gcp_ml_framework.context import MLContext
```

#### Step 4: Verify

```bash
uv run -- pytest tests/components/test_email.py -v
uv run -- ruff check gcp_ml_framework/components/operators/email.py
```

---

### 3c. Add render_operator() to WriteFeatures

#### Current State

`WriteFeatures` (file: `gcp_ml_framework/components/feature_store/write_features.py`) is `@task` but has no `render_operator()`. After 4.5.4, SmartCompiler will raise `NotImplementedError` for it.

WriteFeatures is a metadata-only operation (registers a BQ table as a Feature Store FeatureGroup). There is no native Airflow operator for this — use `PythonOperator`.

#### Step 1: Write Test

**Create file:** `tests/components/test_write_features.py`

```python
"""Unit tests for WriteFeatures (gcp_ml_framework.components.feature_store.write_features)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


class TestWriteFeaturesBasics:
    def test_is_task_type(self):
        assert WriteFeatures._task_type == TaskType.TASK

    def test_instantiation(self):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        assert wf.entity == "user"
        assert wf.feature_group == "churn_signals"


class TestWriteFeaturesRenderOperator:
    def test_has_render_operator(self):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        assert hasattr(wf, "render_operator")
        assert callable(wf.render_operator)

    def test_returns_python_operator(self, mock_context):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        code, imports = wf.render_operator(mock_context)
        assert "PythonOperator" in code
        assert any("PythonOperator" in imp for imp in imports)

    def test_accepts_pipeline_dir_kwarg(self, mock_context):
        wf = WriteFeatures(entity="user", feature_group="churn_signals")
        code, imports = wf.render_operator(mock_context, pipeline_dir=None)
        assert "PythonOperator" in code
```

#### Step 2: Watch Test Fail

```bash
uv run -- pytest tests/components/test_write_features.py -v
```

#### Step 3: Implement

**File:** `gcp_ml_framework/components/feature_store/write_features.py`

Add imports at top. Current imports (lines 1-6):
```python
"""WriteFeatures / ReadFeatures — Feature Store integration components."""

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task
```

Change to:
```python
"""WriteFeatures — Feature Store integration component."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from pathlib import Path

    from gcp_ml_framework.context import MLContext
```

Add `render_operator()` method to `WriteFeatures` class, after `execute()` (after line 47):

```python
    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation.

        WriteFeatures is a metadata-only GCP SDK call with no native Airflow
        operator, so we render as a PythonOperator stub. The actual Feature Store
        registration happens via the Vertex AI SDK at runtime.
        """
        imports = {"from airflow.operators.python import PythonOperator"}

        func_name = f"_write_features_{self.feature_group_id or self.component_name}"
        code = f"""PythonOperator(
        task_id="{{{{ task_id }}}}",
        python_callable={func_name},
    )"""

        return code, imports
```

Note: The `ReadFeatures` class will be deleted in 4.5.5 — do NOT spend time on it.

#### Step 4: Verify

```bash
uv run -- pytest tests/components/test_write_features.py tests/components/test_bq_transform.py tests/components/test_email.py -v
uv run -- ruff check gcp_ml_framework/components/
```

---

<a id="454"></a>
## 4.5.4 — Fix SmartCompiler No-Op Fallback

### Current State

`smart_compiler.py` lines 324-330:
```python
        # Fallback: generate a PythonOperator that calls execute()
        imports = {"from airflow.operators.python import PythonOperator"}
        code = f"""{safe_name} = PythonOperator(
    task_id="{safe_name}",
    python_callable=lambda: None,  # TODO: wire component.execute()
)"""
        return code, imports, safe_name
```

This silently makes `@task` components without `render_operator()` do nothing in production Airflow DAGs.

### Target State

`NotImplementedError` with a helpful error message. All `@task` components that appear in compiled pipelines must implement `render_operator()`.

### Step 1: Write Test

**File:** `tests/pipeline/test_smart_compiler.py` — Add new test class after existing tests:

```python
class TestTaskWithoutRenderOperator:
    def test_task_without_render_operator_raises(self, mock_context, tmp_path):
        """@task component without render_operator() raises NotImplementedError."""

        @task
        class NoRenderTask(BaseComponent):
            component_name: str = "no_render"

        defn = (
            Pipeline(name="fail_test", schedule="@daily")
            .add(NoRenderTask(component_name="no_render"), name="bad_step")
            .build()
        )
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        with pytest.raises(NotImplementedError, match="render_operator"):
            compiler.compile(defn, mock_context)
```

Add `Pipeline` to the imports at top of the file (line 10):

Current:
```python
from gcp_ml_framework.pipeline.builder import Pipeline, PipelineStep
```

This is already imported. Good.

### Step 2: Watch Test Fail

```bash
uv run -- pytest tests/pipeline/test_smart_compiler.py::TestTaskWithoutRenderOperator -v
```

Expected: FAIL — currently returns `lambda: None` instead of raising.

### Step 3: Implement

**File:** `gcp_ml_framework/pipeline/smart_compiler.py`

Replace lines 324-330 (the fallback block) with:

```python
        # No render_operator — fail loud
        raise NotImplementedError(
            f"Component {type(component).__name__} is decorated with @task but does not "
            f"implement render_operator(). All @task components used in compiled pipelines "
            f"must implement render_operator() to generate native Airflow operator code. "
            f"Either add render_operator() to {type(component).__name__} or use a component "
            f"that already has it (e.g. BQQuery, BQTransform, Email)."
        )
```

The full `_render_task_step` method should now be:

```python
    def _render_task_step(
        self,
        step: PipelineStep,
        context: MLContext,
        pipeline_dir: Path | None,
    ) -> tuple[str, set[str], str]:
        """Render a TASK step as a native Airflow operator."""
        component = step.component
        safe_name = step.name.replace(" ", "_").replace("-", "_").lower()

        if hasattr(component, "render_operator"):
            code_template, imports = component.render_operator(context, pipeline_dir=pipeline_dir)
            # Replace the {{ task_id }} placeholder
            code = code_template.replace("{{ task_id }}", safe_name)
            final_code = f"{safe_name} = {code}"
            return final_code, imports, safe_name

        # No render_operator — fail loud
        raise NotImplementedError(
            f"Component {type(component).__name__} is decorated with @task but does not "
            f"implement render_operator(). All @task components used in compiled pipelines "
            f"must implement render_operator() to generate native Airflow operator code. "
            f"Either add render_operator() to {type(component).__name__} or use a component "
            f"that already has it (e.g. BQQuery, BQTransform, Email)."
        )
```

### Step 4: Verify

```bash
uv run -- pytest tests/pipeline/test_smart_compiler.py -v
uv run -- ruff check gcp_ml_framework/pipeline/smart_compiler.py
```

All existing SmartCompiler tests should still pass because they use `BQQuery` and `DummyML` — components that either have `render_operator()` or are `@ml_task`.

---

<a id="455"></a>
## 4.5.5 — Remove Redundant & Broken Components

### Files to Delete

| File | Reason |
|------|--------|
| `gcp_ml_framework/components/ingestion/bigquery_extract.py` | Redundant with BQQuery |
| `gcp_ml_framework/components/ingestion/gcs_extract.py` | Unused, no render_operator |
| `gcp_ml_framework/utils/bigquery_extract.py` | Served only BigQueryExtract |
| `gcp_ml_framework/utils/gcs_extract.py` | Served only GCSExtract |
| `gcp_ml_framework/utils/sql_compat.py` | Dead DuckDB code, nothing imports it |
| `gcp_ml_framework/utils/logging.py` | Dead stdlib logging, loguru used everywhere |

### Files to Edit

**1. Delete `ReadFeatures` class from `write_features.py`**

**File:** `gcp_ml_framework/components/feature_store/write_features.py`

Delete everything from line 50 onwards (the empty line before `@task class ReadFeatures` through end of class at line 65). Keep the `WriteFeatures` class and the `if __name__` block.

After deletion, the file should end with:
```python
    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        # ... (added in 4.5.3)


if __name__ == "__main__":
    WriteFeatures.cli()
```

**2. Delete orphaned `run_read_features()` from `utils/feature_store.py`**

**File:** `gcp_ml_framework/utils/feature_store.py`

Delete `run_read_features()` function (lines 66-103). Keep `run_write_features()` (lines 1-65).

**3. Remove dead code from `builder.py`**

**File:** `gcp_ml_framework/pipeline/builder.py`

Remove from `_STAGE_MAP_BY_NAME` (lines 93-105):
- Delete line `"BigQueryExtract": "ingest",`
- Delete line `"GCSExtract": "ingest",`
- Delete line `"ReadFeatures": "read_features",`

Remove the `read_features()` method from `PipelineBuilder` (lines 159-161):
```python
    def read_features(self, component: BaseComponent, name: str | None = None) -> PipelineBuilder:
        """Add a Feature Store read step."""
        return self._add("read_features", component, name)
```

Remove the `ml_task_groups` property from `PipelineDefinition` (lines 74-85):
```python
    @property
    def ml_task_groups(self) -> list[list[PipelineStep]]:
        """Return groups of consecutive ML_TASK steps.

        Used by SmartCompiler to decide which step sequences become
        Vertex AI pipeline YAML files.
        """
        groups = []
        for task_type, group_iter in groupby(self.steps, key=lambda s: s.task_type):
            if task_type == TaskType.ML_TASK:
                groups.append(list(group_iter))
        return groups
```

Also remove the `from itertools import groupby` import (line 28) since `ml_task_groups` was the only consumer.

**4. Update `tests/components/test_decorators.py`**

Remove the imports and assertions for deleted components:

Change `test_data_components_are_task` (lines 103-117):

Current:
```python
    def test_data_components_are_task(self):
        """BigQueryExtract, BQTransform, WriteFeatures, ReadFeatures, GCSExtract are @task."""
        from gcp_ml_framework.components.feature_store.write_features import (
            ReadFeatures,
            WriteFeatures,
        )
        from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
        from gcp_ml_framework.components.ingestion.gcs_extract import GCSExtract
        from gcp_ml_framework.components.transformation.bq_transform import BQTransform

        assert BigQueryExtract._task_type == TaskType.TASK
        assert GCSExtract._task_type == TaskType.TASK
        assert BQTransform._task_type == TaskType.TASK
        assert WriteFeatures._task_type == TaskType.TASK
        assert ReadFeatures._task_type == TaskType.TASK
```

Replace with:
```python
    def test_data_components_are_task(self):
        """BQTransform, WriteFeatures are @task."""
        from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
        from gcp_ml_framework.components.transformation.bq_transform import BQTransform

        assert BQTransform._task_type == TaskType.TASK
        assert WriteFeatures._task_type == TaskType.TASK
```

**5. Update `tests/pipeline/test_builder.py`**

Remove `.read_features(comp)` calls from test methods:

- Line 38 in `test_builder_chaining`: Remove `.read_features(comp)` from the chain
- Lines 100 and 112 in `test_builder_step_stages`: Remove `.read_features(comp)` and `"read_features"` from expected list

In `test_builder_step_stages`, the expected stages become:
```python
expected_stages = [
    "ingest",
    "transform",
    "write_features",
    "train",
    "evaluate",
    "deploy",
    "custom",
]
```

**6. Update `tests/pipeline/test_unified_builder.py`**

Delete the entire `TestMLTaskGroups` class (lines 119-153) — it tests `PipelineDefinition.ml_task_groups` which we're deleting.

Delete the `TestPipelineInheritance` class (lines 161-171) — tests inheritance from PipelineBuilder which will be deleted in 4.5.6. (Alternatively, keep it until 4.5.6 deletes it.)

Actually — keep `TestPipelineInheritance` for now, it will be cleaned up in 4.5.6.

**7. Remove stage references from `test_unified_builder.py`**

The `test_add_infers_stage_for_known_components` test (lines 41-52) checks `defn.steps[0].stage`. After 4.5.6, `stage` will be removed from `PipelineStep`. But that's 4.5.6, not 4.5.5. For now, leave it.

### Step 1: Delete Files

```bash
rm gcp_ml_framework/components/ingestion/bigquery_extract.py
rm gcp_ml_framework/components/ingestion/gcs_extract.py
rm gcp_ml_framework/utils/bigquery_extract.py
rm gcp_ml_framework/utils/gcs_extract.py
rm gcp_ml_framework/utils/sql_compat.py
rm gcp_ml_framework/utils/logging.py
```

### Step 2: Edit Files

Apply all the edits described above.

### Step 3: Verify

```bash
uv run -- pytest tests/ -m unit -v
uv run -- ruff check gcp_ml_framework/ tests/
# Verify zero references to removed code
grep -r "BigQueryExtract\|GCSExtract\|ReadFeatures\|run_bigquery_extract\|run_gcs_extract\|run_read_features\|sql_compat\|bq_to_duckdb" \
  gcp_ml_framework/ tests/ pipelines/ --include="*.py"
```

Expected: All tests pass, ruff clean, zero grep hits.

---

<a id="456"></a>
## 4.5.6 — Collapse Pipeline API (REQS 11.0)

### Current State

`builder.py` has 225 lines with:
- `PipelineBuilder` class with 8 named stage methods (`.ingest()`, `.transform()`, `.train()`, `.evaluate()`, `.deploy()`, `.write_features()`, `.read_features()`, `.step()`)
- `Pipeline` extends `PipelineBuilder` and adds `.add()`
- `stage` field on `PipelineStep` — set on every step, consumed by nothing
- `_STAGE_MAP_BY_NAME` — maps component class names to stages
- `_infer_stage()` — looks up stage from component class name

### Target State

`builder.py` has ~80 lines with:
- `Pipeline` as a standalone class with only `.add()` and `.build()`
- `PipelineStep` without `stage` field
- No `PipelineBuilder`, no named methods, no stage map

### Step 1: Delete Old Test File

Delete `tests/pipeline/test_builder.py` entirely — all tests use `PipelineBuilder` with named methods.

### Step 2: Add Replacement Tests to `test_unified_builder.py`

**File:** `tests/pipeline/test_unified_builder.py`

Remove the old imports and add these tests. The entire file should be rewritten:

```python
"""Unit tests for Pipeline builder (gcp_ml_framework.pipeline.builder.Pipeline)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType, task
from gcp_ml_framework.pipeline.builder import Pipeline

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyMLComponent(BaseComponent):
    """Inherits default ML_TASK from BaseComponent."""
    component_name: str = "dummy_ml"


@task
class DummyTaskComponent(BaseComponent):
    """Explicitly marked as @task."""
    component_name: str = "dummy_task"


# ---------------------------------------------------------------------------
# Pipeline.add()
# ---------------------------------------------------------------------------


class TestPipelineAdd:
    def test_add_returns_self(self):
        p = Pipeline(name="test")
        result = p.add(DummyMLComponent())
        assert result is p

    def test_add_custom_name(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent(), name="My Custom Step")
            .build()
        )
        assert defn.step_names == ["My Custom Step"]

    def test_add_default_name_uses_class_name(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .build()
        )
        # Default name: {ClassName}_{index}
        assert defn.step_names == ["DummyMLComponent_0"]

    def test_multiple_default_names(self):
        from gcp_ml_framework.components.operators.bq_query import BQQuery

        defn = (
            Pipeline(name="test")
            .add(BQQuery(sql="SELECT 1"))
            .add(DummyMLComponent())
            .build()
        )
        assert defn.step_names == ["BQQuery_0", "DummyMLComponent_1"]


# ---------------------------------------------------------------------------
# Task type propagation
# ---------------------------------------------------------------------------


class TestPipelineTaskTypes:
    def test_task_type_propagated_from_decorator(self):
        defn = (
            Pipeline(name="test")
            .add(DummyTaskComponent(component_name="t"))
            .add(DummyMLComponent())
            .build()
        )
        assert defn.steps[0].task_type == TaskType.TASK
        assert defn.steps[1].task_type == TaskType.ML_TASK

    def test_has_mixed_types_true(self):
        defn = (
            Pipeline(name="test")
            .add(DummyTaskComponent(component_name="t"))
            .add(DummyMLComponent())
            .build()
        )
        assert defn.has_mixed_types is True

    def test_has_mixed_types_false(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .add(DummyMLComponent())
            .build()
        )
        assert defn.has_mixed_types is False


# ---------------------------------------------------------------------------
# Pipeline.build()
# ---------------------------------------------------------------------------


class TestPipelineBuild:
    def test_build_empty_raises(self):
        with pytest.raises(ValueError, match="no steps"):
            Pipeline(name="empty").build()

    def test_build_produces_definition(self):
        defn = (
            Pipeline(name="my-pipeline", schedule="@daily")
            .add(DummyMLComponent())
            .add(DummyMLComponent())
            .build()
        )
        assert defn.name == "my-pipeline"
        assert defn.schedule == "@daily"
        assert len(defn.steps) == 2

    def test_step_names_property(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent(), name="a")
            .add(DummyTaskComponent(component_name="t"), name="b")
            .build()
        )
        assert defn.step_names == ["a", "b"]


# ---------------------------------------------------------------------------
# PipelineStep has no stage field
# ---------------------------------------------------------------------------


class TestPipelineStepNoStage:
    def test_step_has_no_stage(self):
        defn = (
            Pipeline(name="test")
            .add(DummyMLComponent())
            .build()
        )
        assert not hasattr(defn.steps[0], "stage")


# ---------------------------------------------------------------------------
# PipelineBuilder is removed
# ---------------------------------------------------------------------------


class TestPipelineBuilderRemoved:
    def test_pipeline_builder_not_importable(self):
        with pytest.raises(ImportError):
            from gcp_ml_framework.pipeline.builder import PipelineBuilder  # noqa: F401
```

### Step 3: Watch Tests Fail

```bash
uv run -- pytest tests/pipeline/test_unified_builder.py -v
```

Expected: `TestPipelineStepNoStage` and `TestPipelineBuilderRemoved` tests will fail.

### Step 4: Implement

**File:** `gcp_ml_framework/pipeline/builder.py` — Complete rewrite:

```python
"""
Pipeline — fluent builder for ML pipeline definitions.

A data scientist edits exactly one file (pipeline.py) to define their pipeline.
No KFP YAML, no Airflow DAG code, no operator wiring.

Usage:
    pipeline = (
        Pipeline(name="churn-prediction", schedule="0 6 * * 1")
        .add(BQQuery(sql="SELECT ..."))
        .add(TrainModel(machine_type="n2-standard-8"), name="Train Churn Model")
        .add(Email(to=["team@co.com"], subject="Done"))
        .build()
    )
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType


class PipelineStep(BaseModel):
    """A single step in the pipeline, wrapping a component."""

    model_config = {"arbitrary_types_allowed": True}

    name: str
    component: BaseComponent
    task_type: TaskType = TaskType.ML_TASK


class PipelineDefinition(BaseModel):
    """
    The compiled pipeline definition produced by Pipeline.build().

    This is the object passed to:
    - PipelineCompiler / SmartCompiler (→ KFP YAML + Airflow DAG)
    - LocalRunner (→ in-process execution)
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str
    schedule: str | None
    steps: list[PipelineStep] = Field(default_factory=list)
    description: str = ""
    tags: list[str] = Field(default_factory=list)

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self.steps]

    @property
    def has_mixed_types(self) -> bool:
        """True if the pipeline contains both @task and @ml_task steps."""
        types = {s.task_type for s in self.steps}
        return len(types) > 1


class Pipeline:
    """Unified pipeline builder. A pipeline is an ordered sequence of steps.

    Usage:
        pipeline = (
            Pipeline(name="training", schedule="@daily")
            .add(BQQuery(sql="SELECT ..."), name="Ingest")
            .add(TrainModel(), name="Train")
            .add(Email(to=["team@co.com"]), name="Notify")
            .build()
        )
    """

    def __init__(
        self,
        name: str,
        schedule: str | None = "@daily",
        description: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self._name = name
        self._schedule = schedule
        self._description = description
        self._tags = tags or []
        self._steps: list[PipelineStep] = []

    def add(self, component: BaseComponent, name: str | None = None) -> Pipeline:
        """Add a component to the pipeline.

        The task_type is read from the component's _task_type ClassVar
        (set by @task or @ml_task decorator).
        """
        step_name = name or f"{type(component).__name__}_{len(self._steps)}"
        task_type = getattr(component, "_task_type", TaskType.ML_TASK)
        self._steps.append(
            PipelineStep(name=step_name, component=component, task_type=task_type)
        )
        return self

    def build(self) -> PipelineDefinition:
        if not self._steps:
            raise ValueError(
                f"Pipeline '{self._name}' has no steps. "
                "Add at least one step before calling .build()."
            )
        return PipelineDefinition(
            name=self._name,
            schedule=self._schedule,
            steps=list(self._steps),
            description=self._description,
            tags=self._tags,
        )
```

### Step 5: Update Exports

**File:** `gcp_ml_framework/__init__.py`

Current (lines 1-15):
```python
"""GCP ML Framework — branch-isolated ML pipelines on GCP."""

__version__ = "0.1.0"

from gcp_ml_framework.decorators import TaskType, ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline, PipelineBuilder

__all__ = [
    "Pipeline",
    "PipelineBuilder",
    "TaskType",
    "ml_task",
    "task",
]
```

Change to:
```python
"""GCP ML Framework — branch-isolated ML pipelines on GCP."""

__version__ = "0.1.0"

from gcp_ml_framework.decorators import TaskType, ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline

__all__ = [
    "Pipeline",
    "TaskType",
    "ml_task",
    "task",
]
```

**File:** `gcp_ml_framework/pipeline/__init__.py`

Current (lines 1-4):
```python
# pipeline package
from gcp_ml_framework.pipeline.builder import PipelineBuilder, PipelineDefinition

__all__ = ["PipelineBuilder", "PipelineDefinition"]
```

Change to:
```python
# pipeline package
from gcp_ml_framework.pipeline.builder import Pipeline, PipelineDefinition

__all__ = ["Pipeline", "PipelineDefinition"]
```

### Step 6: Add Component Import Facade

**File:** `gcp_ml_framework/components/__init__.py`

Current:
```python
# components package
```

Change to:
```python
"""Component re-exports for data scientist convenience.

Usage:
    from gcp_ml_framework.components import BQQuery, TrainModel
"""

from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.deploy import DeployModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.register import RegisterModel
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.operators.email import Email
from gcp_ml_framework.components.transformation.bq_transform import BQTransform

__all__ = [
    "BQQuery",
    "BQTransform",
    "DeployModel",
    "Email",
    "EvaluateModel",
    "RegisterModel",
    "TrainModel",
    "WriteFeatures",
]
```

### Step 7: Update SmartCompiler References

The `SmartCompiler` constructs `PipelineStep` objects in `_compile_ml_group()` which creates a sub-`PipelineDefinition`. The `PipelineStep` no longer has a `stage` field. Check that `_compile_ml_group` doesn't reference `stage`.

Looking at `smart_compiler.py:124-130`:
```python
sub_def = PipelineDef(
    name=group_name,
    schedule=pipeline_def.schedule,
    steps=group.steps,
    description=pipeline_def.description,
    tags=pipeline_def.tags,
)
```

This passes `group.steps` directly — the existing `PipelineStep` objects. Since we're removing `stage` from `PipelineStep`, these objects won't have `stage` anymore, which is fine because nothing in the compiler reads `stage`.

### Step 8: Update test_compiler.py

**File:** `tests/pipeline/test_compiler.py`

Replace `PipelineBuilder` usage with `Pipeline`:

Line 9 — Change import:
```python
from gcp_ml_framework.pipeline.builder import PipelineBuilder
```
to:
```python
from gcp_ml_framework.pipeline.builder import Pipeline
```

Line 45 — Change:
```python
defn = PipelineBuilder(name="test-pipe").ingest(comp).build()
```
to:
```python
defn = Pipeline(name="test-pipe").add(comp).build()
```

Line 79 — Change:
```python
defn = PipelineBuilder(name="env-pipe").ingest(comp).build()
```
to:
```python
defn = Pipeline(name="env-pipe").add(comp).build()
```

Line 99 — Change:
```python
defn = PipelineBuilder(name="train-pipe").train(train, name="train_0").build()
```
to:
```python
defn = Pipeline(name="train-pipe").add(train, name="train_0").build()
```

### Step 9: Update test_smart_compiler.py

**File:** `tests/pipeline/test_smart_compiler.py`

`PipelineStep` constructors in this file include `stage=` kwarg. Remove all `stage=` kwargs.

Lines 38-42:
```python
PipelineStep(
    name="a", component=DummyML(),
    stage="train", task_type=TaskType.ML_TASK,
),
```
Change to:
```python
PipelineStep(
    name="a", component=DummyML(),
    task_type=TaskType.ML_TASK,
),
```

Apply the same pattern to ALL `PipelineStep(...)` constructors in this file (lines 38, 43, 56, 58, 62, 66, 79, 84, 211-220).

### Step 10: Delete test_builder.py

```bash
rm tests/pipeline/test_builder.py
```

### Step 11: Verify

```bash
uv run -- pytest tests/pipeline/ -v
uv run -- ruff check gcp_ml_framework/pipeline/ tests/pipeline/
# Zero hits for dead API:
grep -r "PipelineBuilder\|_STAGE_MAP\|_infer_stage\|\.ingest(\|\.transform(\|\.train(\|\.evaluate(\|\.deploy(\|\.write_features(\|\.read_features(\|\.step(" \
  gcp_ml_framework/ tests/ pipelines/ --include="*.py"
```

---

<a id="457"></a>
## 4.5.7 — Create verification_pipeline

### Purpose

A mixed `@task` + `@ml_task` pipeline that proves the SmartCompiler works end-to-end with both types.

### Step 1: Create Pipeline Files

**Create:** `pipelines/verification_pipeline/__init__.py` — empty file

**Create:** `pipelines/verification_pipeline/steps/__init__.py` — empty file

**Create:** `pipelines/verification_pipeline/steps/train_verify_model.py`:

```python
"""Simple training step for verification — trains on verification_features table."""

import pickle
from pathlib import Path

from loguru import logger

from gcp_ml_framework.components.ml.train import TrainModel


class TrainVerifyModelStep(TrainModel):
    """Minimal training step for architecture verification."""

    def run(self) -> None:
        from google.cloud import bigquery

        from second_run.estimator import HousePredictionModel

        logger.info(f"[train_verify_model] project={self.project}, dataset={self.dataset}")
        client = bigquery.Client(project=self.project)
        query = f"SELECT * FROM `{self.dataset}.verification_features`"
        df = client.query(query).to_dataframe()

        model = HousePredictionModel()
        model.fit(df, df["price"])

        local_path = Path(self._work_dir) / "model.pkl"
        with open(local_path, "wb") as f:
            pickle.dump(model, f)
        logger.info(f"[train_verify_model] Model saved to {local_path}")
```

**Create:** `pipelines/verification_pipeline/pipeline.py`:

```python
"""Verification pipeline — mixed @task + @ml_task to prove SmartCompiler architecture."""

from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.transformation.bq_transform import BQTransform

from pipelines.verification_pipeline.steps.train_verify_model import TrainVerifyModelStep

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
    .build()
)
```

### Step 2: Verify It Compiles

```bash
UV_ENV_FILE=.env uv run -- gml compile verification_pipeline
```

Check that `compiled_pipelines/verification_pipeline.yaml` and `dags/mlplatform_second_run_*_verification_pipeline.py` are created.

Inspect the DAG:
- Should contain `BigQueryInsertJobOperator` (2x — one for BQQuery, one for BQTransform)
- Should contain `RunPipelineJobOperator` (1x — for the train ML group)
- Should have sequential dependencies

---

<a id="458"></a>
## 4.5.8 — Tests for verification_pipeline

### Step 1: Create Test Files

**Create:** `tests/verification_pipeline/__init__.py` — empty file

**Create:** `tests/verification_pipeline/test_compile.py`:

```python
"""Unit tests for verification_pipeline compilation."""

from __future__ import annotations

import pytest

from gcp_ml_framework.decorators import TaskType
from gcp_ml_framework.pipeline.smart_compiler import SmartCompiler

pytestmark = pytest.mark.unit


def _load_pipeline():
    """Import and return the verification pipeline definition."""
    from pipelines.verification_pipeline.pipeline import pipeline
    return pipeline


class TestVerificationPipelineStructure:
    def test_step_count(self):
        defn = _load_pipeline()
        assert len(defn.steps) == 3

    def test_mixed_types(self):
        defn = _load_pipeline()
        assert defn.has_mixed_types is True

    def test_step_names(self):
        defn = _load_pipeline()
        assert defn.step_names == ["Ingest Raw Data", "Transform Features", "Train Model"]

    def test_task_types(self):
        defn = _load_pipeline()
        assert defn.steps[0].task_type == TaskType.TASK
        assert defn.steps[1].task_type == TaskType.TASK
        assert defn.steps[2].task_type == TaskType.ML_TASK


class TestVerificationPipelineCompile:
    def test_compiles_without_error(self, mock_context, tmp_path):
        defn = _load_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        assert result.dag_path.exists()

    def test_dag_has_bq_operators(self, mock_context, tmp_path):
        defn = _load_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        content = result.dag_path.read_text()
        assert content.count("BigQueryInsertJobOperator") >= 2

    def test_dag_has_vertex_operator(self, mock_context, tmp_path):
        defn = _load_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        content = result.dag_path.read_text()
        assert "RunPipelineJobOperator" in content

    def test_yaml_produced(self, mock_context, tmp_path):
        defn = _load_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        assert len(result.yaml_paths) == 1

    def test_dag_has_dependencies(self, mock_context, tmp_path):
        defn = _load_pipeline()
        compiler = SmartCompiler(
            output_dir=tmp_path / "compiled",
            dags_dir=tmp_path / "dags",
        )
        try:
            result = compiler.compile(defn, mock_context)
        except ImportError:
            pytest.skip("kfp not installed")
        content = result.dag_path.read_text()
        # Should have >> dependency chains
        assert ">>" in content
```

### Step 2: Verify

```bash
uv run -- pytest tests/verification_pipeline/ -v
uv run -- pytest tests/ -m unit -v
```

---

<a id="459"></a>
## 4.5.9 — Fix CLI Bugs

### 9a. Fix cmd_deploy.py Error Swallowing

#### Current State

`cmd_deploy.py` line 58-59:
```python
    except SystemExit:
        pass  # compile_cmd uses typer.Exit for flow control
```

If compilation fails, deploy continues deploying broken artifacts.

#### Step 1: Implement

**File:** `gcp_ml_framework/cli/cmd_deploy.py`

Replace lines 58-59:
```python
    except SystemExit:
        pass  # compile_cmd uses typer.Exit for flow control
```

With:
```python
    except SystemExit as e:
        if e.code and e.code != 0:
            err_console.print("[red]Compilation failed — aborting deploy[/red]")
            raise typer.Exit(1) from e
```

Add `err_console` import if not already present. Check the imports at top of `cmd_deploy.py` — it already imports from `_helpers`:
```python
from gcp_ml_framework.cli._helpers import console, err_console, load_context
```

Good, `err_console` is already available.

#### Step 2: Verify

No specific test needed — this is defensive error handling. Verify existing CLI tests still pass:

```bash
uv run -- pytest tests/cli/ -v
```

---

### 9b. Fix cmd_init.py Scaffolded CI Templates

#### Step 1: Implement

**File:** `gcp_ml_framework/cli/cmd_init.py`

**Fix 1 — Line 123:** Change `gml run --compile-only --all` to `gml compile --all`:
```python
      - run: gml compile --all
```

**Fix 2 — Lines 124-125:** Change `gml deploy dags` and `gml deploy features` to `gml deploy --all`:
```python
      - run: gml deploy --all
```

**Fix 3 — Line 184:** Change `gml promote --from main --to prod --tag ...` to a comment explaining promotion is not yet implemented:
```python
      - run: echo "Promotion not yet implemented — manually copy artifacts"
```

**Fix 4 — Line 261:** Change `.python-version` from `3.11` to `3.12`:
```python
    _write(root / ".python-version", "3.12\n")
```

#### Step 2: Verify

```bash
uv run -- ruff check gcp_ml_framework/cli/cmd_init.py
```

---

### 9c. Extract Duplicated `_load_pipeline()`

#### Current State

Identical `_load_pipeline()` function exists in:
- `gcp_ml_framework/cli/cmd_compile.py` (lines 86-103)
- `gcp_ml_framework/cli/cmd_run.py` (lines 13-32)

#### Step 1: Implement

**File:** `gcp_ml_framework/cli/_helpers.py`

Add the shared function at the end of the file (after `print_kv_table`):

```python
def load_pipeline(pipeline_dir: Path):
    """Import a pipeline.py and return its `pipeline` object."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_pipeline", pipeline_dir / "pipeline.py"
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"No pipeline.py found in {pipeline_dir}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pipeline"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not hasattr(mod, "pipeline"):
        raise AttributeError(
            f"{pipeline_dir}/pipeline.py must define a `pipeline` variable"
        )
    return mod.pipeline
```

**File:** `gcp_ml_framework/cli/cmd_compile.py`

Delete the `_load_pipeline()` function (lines 86-103).

Update the import and usage. Find where `_load_pipeline` is called in `cmd_compile.py` and replace with import from `_helpers`:

Add to imports at top:
```python
from gcp_ml_framework.cli._helpers import load_pipeline
```

Replace all calls from `_load_pipeline(...)` to `load_pipeline(...)`.

**File:** `gcp_ml_framework/cli/cmd_run.py`

Delete the `_load_pipeline()` function (lines 13-32).

Add to imports at top:
```python
from gcp_ml_framework.cli._helpers import load_pipeline
```

Replace all calls from `_load_pipeline(...)` to `load_pipeline(...)`.

#### Step 2: Verify

```bash
uv run -- pytest tests/cli/ -v
uv run -- ruff check gcp_ml_framework/cli/
# Verify no duplicate:
grep -r "_load_pipeline\|def _load_pipeline" gcp_ml_framework/cli/ --include="*.py"
# Should only show imports, not definitions (except in _helpers.py)
```

---

<a id="4510"></a>
## 4.5.10 — Full Verification

### Run All Tests

```bash
uv run -- pytest tests/ -m unit -v
```

Expected: All pass. Count should be ~155-165 (some tests deleted, many added).

### Run Ruff

```bash
uv run -- ruff check gcp_ml_framework/ tests/
```

Expected: Zero errors.

### Compile Both Pipelines

```bash
UV_ENV_FILE=.env uv run -- gml compile --all
```

Expected: Both training_pipeline and verification_pipeline compile successfully.

### Inspect Verification Pipeline DAG

```bash
cat dags/mlplatform_second_run_*_verification_pipeline.py
```

Expected contents:
- 2x `BigQueryInsertJobOperator` (Ingest + Transform)
- 1x `RunPipelineJobOperator` (Train)
- Sequential dependencies (`>>`)

### Run Locally (Requires GCP Auth + Seeded BQ Data)

```bash
UV_ENV_FILE=.env uv run -- gml run verification_pipeline --local
```

### Zero Dead Code

```bash
grep -r "sql_compat\|bq_to_duckdb\|from gcp_ml_framework.utils.logging\|get_logger\|ml_task_groups\|PipelineBuilder\|_STAGE_MAP\|_infer_stage\|BigQueryExtract\|GCSExtract\|ReadFeatures" \
  gcp_ml_framework/ tests/ pipelines/ --include="*.py"
```

Expected: Zero hits.

### CLI Verification

```bash
UV_ENV_FILE=.env uv run -- gml --help
UV_ENV_FILE=.env uv run -- gml context show
```

---

## File Change Summary

### Files DELETED (7)

| File | Reason |
|------|--------|
| `gcp_ml_framework/components/ingestion/bigquery_extract.py` | Redundant with BQQuery |
| `gcp_ml_framework/components/ingestion/gcs_extract.py` | Unused, no render_operator |
| `gcp_ml_framework/utils/bigquery_extract.py` | Served only BigQueryExtract |
| `gcp_ml_framework/utils/gcs_extract.py` | Served only GCSExtract |
| `gcp_ml_framework/utils/sql_compat.py` | Dead DuckDB code |
| `gcp_ml_framework/utils/logging.py` | Dead stdlib logging |
| `tests/pipeline/test_builder.py` | All tests used deleted PipelineBuilder |

### Files CREATED (7)

| File | Purpose |
|------|---------|
| `tests/components/test_bq_transform.py` | BQTransform render_operator tests |
| `tests/components/test_write_features.py` | WriteFeatures render_operator tests |
| `tests/verification_pipeline/__init__.py` | Test package |
| `tests/verification_pipeline/test_compile.py` | Verification pipeline compilation tests |
| `pipelines/verification_pipeline/__init__.py` | Pipeline package |
| `pipelines/verification_pipeline/steps/__init__.py` | Steps package |
| `pipelines/verification_pipeline/steps/train_verify_model.py` | Verification training step |
| `pipelines/verification_pipeline/pipeline.py` | Verification pipeline definition |

### Files MODIFIED (17)

| File | Changes |
|------|---------|
| `gcp_ml_framework/components/ml/train.py` | Add `@ml_task` decorator + import |
| `gcp_ml_framework/components/ml/evaluate.py` | Add `@ml_task`, refactor execute()→run() |
| `gcp_ml_framework/components/ml/register.py` | Add `@ml_task`, refactor execute()→run() |
| `gcp_ml_framework/components/ml/deploy.py` | Add `@ml_task`, refactor execute()→run() |
| `gcp_ml_framework/components/operators/email.py` | Add `pipeline_dir` to render_operator() |
| `gcp_ml_framework/components/transformation/bq_transform.py` | Add render_operator() |
| `gcp_ml_framework/components/feature_store/write_features.py` | Add render_operator(), delete ReadFeatures |
| `gcp_ml_framework/pipeline/builder.py` | Complete rewrite: delete PipelineBuilder, stage, named methods |
| `gcp_ml_framework/pipeline/smart_compiler.py` | Replace lambda:None with NotImplementedError |
| `gcp_ml_framework/__init__.py` | Remove PipelineBuilder export |
| `gcp_ml_framework/pipeline/__init__.py` | Replace PipelineBuilder with Pipeline |
| `gcp_ml_framework/components/__init__.py` | Add import facade |
| `gcp_ml_framework/utils/feature_store.py` | Delete run_read_features() |
| `gcp_ml_framework/cli/cmd_deploy.py` | Fix SystemExit handling |
| `gcp_ml_framework/cli/cmd_init.py` | Fix scaffolded CI commands + Python version |
| `gcp_ml_framework/cli/cmd_compile.py` | Delete _load_pipeline(), import from _helpers |
| `gcp_ml_framework/cli/cmd_run.py` | Delete _load_pipeline(), import from _helpers |
| `gcp_ml_framework/cli/_helpers.py` | Add shared load_pipeline() |
| `tests/components/test_decorators.py` | Remove deleted component imports |
| `tests/components/test_evaluate.py` | Add lifecycle tests |
| `tests/components/test_register.py` | Add lifecycle tests |
| `tests/components/test_deploy.py` | Add lifecycle tests |
| `tests/components/test_email.py` | Add render_operator tests |
| `tests/pipeline/test_unified_builder.py` | Rewrite: replace PipelineBuilder tests |
| `tests/pipeline/test_compiler.py` | Replace PipelineBuilder with Pipeline |
| `tests/pipeline/test_smart_compiler.py` | Remove stage kwargs, add NotImplementedError test |

---

## Execution Order (Dependencies)

```
4.5.1 (decorators)      — no deps
4.5.2 (execute→run)     — no deps
4.5.3 (render_operator) — no deps
        ↓ (4.5.4 depends on 4.5.3: all @task components must have render_operator first)
4.5.4 (NotImplementedError)
        ↓ (4.5.5 depends on 4.5.4: deleted components would trigger NotImplementedError)
4.5.5 (delete dead code)
        ↓ (4.5.6 depends on 4.5.5: builder.py references deleted components in stage map)
4.5.6 (collapse Pipeline API)
        ↓ (4.5.7 depends on 4.5.6: verification_pipeline uses Pipeline.add())
4.5.7 (verification_pipeline)
4.5.8 (verification tests) — depends on 4.5.7
4.5.9 (CLI bugs)           — independent, can run anytime after 4.5.6
4.5.10 (full verification) — last
```

Tasks 4.5.1, 4.5.2, and 4.5.3 can be done in parallel.

---

## Checkpoint After Each Sub-task

After completing each sub-task, run:

```bash
uv run -- pytest tests/ -m unit -v
uv run -- ruff check gcp_ml_framework/ tests/
```

Both must pass before moving to the next sub-task. If either fails, fix before proceeding.
