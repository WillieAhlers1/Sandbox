# Testing Guide

## Three-Tier Strategy

| Tier | Marker | GCP Credentials | Speed | What It Tests |
|------|--------|----------------|-------|---------------|
| **Unit** | `@pytest.mark.unit` | No | Fast (~seconds) | Logic, parameter wiring, component contracts, compiler output |
| **Integration** | `@pytest.mark.integration` | Yes (dev project) | Medium (~minutes) | Real GCP SDK calls against dev resources |
| **E2E** | `@pytest.mark.e2e` | Yes (dev project) | Slow (~10+ min) | Full pipeline compile + run on Vertex AI |

Unit tests mock all GCP interactions. Integration tests hit real GCP dev resources. E2E tests run the full pipeline lifecycle.

## Running Tests

```bash
# All unit tests
uv run -- pytest tests/ -m unit -v

# All integration tests (requires GCP auth + .env)
UV_ENV_FILE=.env uv run -- pytest tests/ -m integration -v

# All e2e tests (requires GCP auth + seeded BQ data)
UV_ENV_FILE=.env uv run -- pytest tests/ -m e2e -v

# Specific test file
uv run -- pytest tests/components/test_train.py -v

# Specific test class
uv run -- pytest tests/pipeline/test_compiler.py::TestBuildContextParamsKeys -v

# With coverage
uv run -- pytest tests/ -m unit --cov=gcp_ml_framework --cov-report=term-missing
```

## pytest Configuration

Defined in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "unit: Fast tests, no GCP credentials needed",
    "integration: Requires GCP credentials and dev project",
    "e2e: Full pipeline execution on GCP (slow)",
]
addopts = "-v --tb=short"
```

## Shared Fixtures (conftest.py)

`tests/conftest.py` provides four core fixtures used across all unit tests:

### mock_naming

```python
@pytest.fixture
def mock_naming() -> NamingConvention:
    return NamingConvention(
        team="testteam",
        project="testproject",
        branch="test-branch",
        gcp_project="test-gcp-project",
    )
```

Use when testing anything that needs a `NamingConvention` instance (resource name derivation, image URIs).

### mock_gcp_config

```python
@pytest.fixture
def mock_gcp_config() -> GCPConfig:
    return GCPConfig(
        project_id="test-gcp-project",
        region="us-central1",
    )
```

Use when testing code that reads GCP configuration.

### mock_framework_config

```python
@pytest.fixture
def mock_framework_config(mock_gcp_config: GCPConfig) -> FrameworkConfig:
    # Patches ENVIRONMENT env var to "dev"
    return FrameworkConfig(
        team="testteam", project="testproject",
        branch="test-branch", environment="dev",
        gcp=mock_gcp_config,
    )
```

Use when testing code that needs the full config object.

### mock_context

```python
@pytest.fixture
def mock_context(mock_framework_config: FrameworkConfig) -> MLContext:
    return MLContext.from_config(mock_framework_config)
```

Use when testing components, the compiler, or anything that receives `MLContext`. This is the most commonly used fixture.

## Test Patterns

### Unit Test Structure

Every test file follows this pattern:

```python
"""Unit tests for ModuleName (gcp_ml_framework.module.path)."""
from __future__ import annotations
import pytest
from gcp_ml_framework.components.base import BaseComponent

pytestmark = pytest.mark.unit  # Marks ALL tests in this file as unit

class TestFeatureGroup:
    """Docstring describing what this group tests."""

    def test_specific_behavior(self):
        """One-line description of the expected behavior."""
        # Arrange
        comp = BaseComponent()
        # Act
        result = comp.some_method()
        # Assert
        assert result == expected
```

Key conventions:
- `pytestmark = pytest.mark.unit` at module level (not per-test)
- Test classes group related tests (e.g., `TestTrainModelInstantiation`, `TestTrainModelExecute`)
- Each test method has a docstring explaining expected behavior
- Use `@patch` for GCP SDK calls, never hit real services in unit tests

### Mocking GCP Services

```python
from unittest.mock import MagicMock, patch

class TestTrainModelExecute:
    @patch("gcp_ml_framework.utils.gcs.upload_file")
    def test_execute_uploads(self, mock_upload: MagicMock) -> None:
        class _TestTrainer(TrainModel):
            def run(self) -> None:
                (self._work_dir / "model.pkl").write_text("fake-model")

        trainer = _TestTrainer(model_output_uri="gs://bucket/models/test", project="test")
        trainer.execute()

        mock_upload.assert_called_once()
```

Pattern: Patch the utility function (e.g., `gcp_ml_framework.utils.gcs.upload_file`), not the GCP SDK directly. This keeps tests stable when SDK internals change.

### Testing Components

Subclass the component, override `run()` with test logic, then call `execute()`:

```python
class _TestTrainer(TrainModel):
    def run(self) -> None:
        (self._work_dir / "model.pkl").write_bytes(b"fake")

trainer = _TestTrainer(model_output_uri="gs://bucket/out", project="test")
trainer.execute()
```

### Testing the Compiler

Use `mock_context` and verify derived parameters:

```python
def test_context_params(self, mock_context, tmp_path):
    compiler = PipelineCompiler(output_dir=tmp_path)
    comp = DummyComponent()
    defn = Pipeline(name="test-pipe").add(comp).build()
    params = compiler._build_context_params(mock_context, defn)
    assert params["environment"] == "dev"
```

### E2E Tests

E2E tests run real pipelines and require:
1. GCP authentication (`gcloud auth application-default login`)
2. `.env` with real GCP project values
3. Seeded BigQuery data

```python
@pytest.mark.e2e
class TestTrainingPipelineE2E:
    def test_compile_produces_yaml(self):
        ctx = load_context()
        compiler = SmartCompiler()
        result = compiler.compile(pipeline_def, ctx, pipeline_dir=pipeline_dir)
        assert result.dag_path.exists()

    def test_local_run_completes(self):
        result = subprocess.run(
            [sys.executable, "-m", "gcp_ml_framework.cli.main",
             "run", "training_pipeline", "--local"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0
```

## Test File Organization

```
tests/
  conftest.py                        # Shared fixtures (mock_context, mock_naming, etc.)
  __init__.py
  components/
    test_base.py                     # BaseComponent fields, CLI, run/execute contract
    test_train.py                    # TrainModel lifecycle, experiment tracking
    test_evaluate.py                 # EvaluateModel
    test_register.py                 # RegisterModel (serving image ownership)
    test_deploy.py                   # DeployModel (no serving image)
    test_bq_query.py                 # BigQuery query operator
    test_bq_transform.py            # BQ transform
    test_write_features.py          # Feature store writes
    test_email.py                   # Email operator
    test_decorators.py              # @task / @ml_task decorators
    test_dbt_run.py                 # dbt integration
  pipeline/
    test_unified_builder.py          # Pipeline.add() API
    test_compiler.py                 # PipelineCompiler parameter derivation
    test_smart_compiler.py           # SmartCompiler (KFP + Airflow output)
    test_local_runner.py             # Local pipeline execution
    test_builder_loops.py            # Loop/conditional operators
    test_compiler_loops.py           # Loop compilation
    test_pipeline_definitions.py     # Pipeline definition validation
  config/
    test_config.py                   # FrameworkConfig, GCPConfig loading
    test_context.py                  # MLContext.from_config()
    test_naming.py                   # NamingConvention resource derivation
  cli/
    test_commands.py                 # CLI command tests
  utils/
    test_vertex.py                   # Vertex AI utilities
    test_evaluate.py                 # Evaluation utilities
  training_pipeline/
    test_e2e.py                      # E2E: compile + local run
  verification_pipeline/
    test_compile.py                  # Verification pipeline compilation
  house_price/
    test_imports.py                  # Import smoke tests
```

## TDD Workflow

This project follows strict TDD. For every change:

1. **Write a failing test** that describes the expected behavior
2. **Run it** to confirm it fails (`uv run -- pytest tests/path/test_file.py::TestClass::test_method -v`)
3. **Implement** the minimum code to make it pass
4. **Run all unit tests** to verify no regressions (`uv run -- pytest tests/ -m unit -v`)
5. **Refactor** if needed, re-run tests
6. **Run quality gates:**
   ```bash
   uv run -- ruff check gcp_ml_framework tests
   uv run -- mypy gcp_ml_framework/
   uv run -- pytest tests/ -m unit -v
   ```

## Quality Gates

Every change must pass all of these before it is considered done:

```bash
# Lint (zero errors)
uv run -- ruff check gcp_ml_framework tests

# Type check (zero errors)
uv run -- mypy gcp_ml_framework/

# Unit tests (all pass)
uv run -- pytest tests/ -m unit -v

# Compile check (no errors)
UV_ENV_FILE=.env uv run -- gml compile --all
```
