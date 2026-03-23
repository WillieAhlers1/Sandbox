"""Unit tests for LocalRunner (gcp_ml_framework.pipeline.local_runner)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task
from gcp_ml_framework.pipeline.builder import Pipeline
from gcp_ml_framework.pipeline.local_runner import LocalRunner

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_execute_log: list[str] = []


class TrackingMLComponent(BaseComponent):
    component_name: str = "tracking_ml"

    def execute(self):
        _execute_log.append("ml")


@task
class TrackingTaskComponent(BaseComponent):
    component_name: str = "tracking_task"

    def execute(self):
        _execute_log.append("task")


@pytest.fixture(autouse=True)
def clear_log():
    _execute_log.clear()
    yield


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


class TestLocalRunnerBasic:
    def test_runs_all_steps(self, mock_context):
        """LocalRunner executes all steps in order."""
        defn = (
            Pipeline(name="test_pipeline", schedule="@daily")
            .add(TrackingTaskComponent(component_name="step1"))
            .add(TrackingMLComponent(component_name="step2"))
            .build()
        )
        runner = LocalRunner()
        runner.run(defn, mock_context, run_date="2026-03-20")
        assert len(_execute_log) == 2
        assert _execute_log[0] == "task"
        assert _execute_log[1] == "ml"

    def test_injects_context_params(self, mock_context):
        """LocalRunner injects context params (project, region, etc.)."""
        received_params = {}

        class ParamCapture(BaseComponent):
            component_name: str = "capture"

            def execute(self):
                received_params["project"] = self.project
                received_params["region"] = self.region
                received_params["environment"] = self.environment

        defn = (
            Pipeline(name="test_pipeline")
            .add(ParamCapture(component_name="capture"), name="cap")
            .build()
        )
        runner = LocalRunner()
        runner.run(defn, mock_context, run_date="2026-03-20")
        assert received_params["project"] == mock_context.gcp_project
        assert received_params["region"] == mock_context.region

    def test_injects_run_date(self, mock_context):
        """LocalRunner injects run_date param."""
        captured_date = {}

        class DateCapture(BaseComponent):
            component_name: str = "date_cap"

            def execute(self):
                captured_date["run_date"] = self.run_date

        defn = (
            Pipeline(name="test_pipeline")
            .add(DateCapture(component_name="date_cap"), name="dc")
            .build()
        )
        runner = LocalRunner()
        runner.run(defn, mock_context, run_date="2026-01-15")
        assert captured_date["run_date"] == "2026-01-15"


# ---------------------------------------------------------------------------
# Default run_date
# ---------------------------------------------------------------------------


class TestLocalRunnerDefaults:
    def test_default_run_date_is_today(self, mock_context):
        """When no run_date is given, defaults to today."""
        import datetime

        captured = {}

        class DateCapture(BaseComponent):
            component_name: str = "dc"

            def execute(self):
                captured["run_date"] = self.run_date

        defn = Pipeline(name="test").add(DateCapture(component_name="dc"), name="dc").build()
        runner = LocalRunner()
        runner.run(defn, mock_context)
        assert captured["run_date"] == datetime.date.today().isoformat()


# ---------------------------------------------------------------------------
# Mixed pipeline
# ---------------------------------------------------------------------------


class TestLocalRunnerMixed:
    def test_runs_mixed_task_types(self, mock_context):
        """LocalRunner handles mixed @task and @ml_task steps."""
        defn = (
            Pipeline(name="mixed")
            .add(TrackingTaskComponent(component_name="ingest"))
            .add(TrackingMLComponent(component_name="train"))
            .add(TrackingTaskComponent(component_name="notify"))
            .build()
        )
        runner = LocalRunner()
        runner.run(defn, mock_context, run_date="2026-03-20")
        assert _execute_log == ["task", "ml", "task"]
