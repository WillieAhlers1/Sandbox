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
