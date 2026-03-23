"""GCP ML Framework — branch-isolated ML pipelines on GCP."""

__version__ = "0.1.0"

from gcp_ml_framework.decorators import ml_task, task
from gcp_ml_framework.pipeline.builder import Pipeline
from gcp_ml_framework.types import TaskType

__all__ = [
    "Pipeline",
    "TaskType",
    "ml_task",
    "task",
]
