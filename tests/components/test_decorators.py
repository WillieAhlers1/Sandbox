"""Unit tests for decorators (gcp_ml_framework.decorators)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import TaskType, ml_task, task

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# TaskType enum
# ---------------------------------------------------------------------------


class TestTaskTypeEnum:
    def test_task_type_values(self):
        assert TaskType.TASK == "task"
        assert TaskType.ML_TASK == "ml_task"

    def test_task_type_is_str(self):
        assert isinstance(TaskType.TASK, str)
        assert isinstance(TaskType.ML_TASK, str)


# ---------------------------------------------------------------------------
# @task decorator
# ---------------------------------------------------------------------------


class TestTaskDecorator:
    def test_task_sets_type(self):
        @task
        class MyTask(BaseComponent):
            component_name: str = "my_task"

        assert MyTask._task_type == TaskType.TASK

    def test_task_returns_class(self):
        @task
        class MyTask(BaseComponent):
            component_name: str = "my_task"

        assert isinstance(MyTask(component_name="my_task"), BaseComponent)


# ---------------------------------------------------------------------------
# @ml_task decorator
# ---------------------------------------------------------------------------


class TestMlTaskDecorator:
    def test_ml_task_sets_type_bare(self):
        """@ml_task without arguments."""
        @ml_task
        class MyMLTask(BaseComponent):
            component_name: str = "my_ml_task"

        assert MyMLTask._task_type == TaskType.ML_TASK

    def test_ml_task_with_resource_params(self):
        """@ml_task(machine_type=...) overrides field defaults."""
        @ml_task(
            machine_type="a2-highgpu-1g",
            accelerator_type="NVIDIA_TESLA_A100",
            accelerator_count=1,
        )
        class BigMLTask(BaseComponent):
            component_name: str = "big_ml"

        assert BigMLTask._task_type == TaskType.ML_TASK
        # Field defaults should be overridden
        instance = BigMLTask(component_name="big_ml")
        assert instance.machine_type == "a2-highgpu-1g"
        assert instance.accelerator_type == "NVIDIA_TESLA_A100"
        assert instance.accelerator_count == 1


# ---------------------------------------------------------------------------
# Default task types on existing components
# ---------------------------------------------------------------------------


class TestDefaultTaskTypes:
    def test_base_component_default_ml_task(self):
        """BaseComponent defaults to ML_TASK."""
        assert BaseComponent._task_type == TaskType.ML_TASK

    def test_ml_components_are_ml_task(self):
        """TrainModel, EvaluateModel, RegisterModel, DeployModel inherit ML_TASK."""
        from gcp_ml_framework.components.ml.deploy import DeployModel
        from gcp_ml_framework.components.ml.evaluate import EvaluateModel
        from gcp_ml_framework.components.ml.register import RegisterModel
        from gcp_ml_framework.components.ml.train import TrainModel

        assert TrainModel._task_type == TaskType.ML_TASK
        assert EvaluateModel._task_type == TaskType.ML_TASK
        assert RegisterModel._task_type == TaskType.ML_TASK
        assert DeployModel._task_type == TaskType.ML_TASK

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

    def test_operator_components_are_task(self):
        """BQQuery and Email are @task."""
        from gcp_ml_framework.components.operators.bq_query import BQQuery
        from gcp_ml_framework.components.operators.email import Email

        assert BQQuery._task_type == TaskType.TASK
        assert Email._task_type == TaskType.TASK
