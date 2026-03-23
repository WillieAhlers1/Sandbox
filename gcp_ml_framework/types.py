"""Shared type definitions — no framework imports to avoid circular dependencies."""

from enum import StrEnum


class TaskType(StrEnum):
    """Discriminator for how a component is compiled."""

    TASK = "task"  # Airflow operator (BQ, email, etc.)
    ML_TASK = "ml_task"  # Vertex AI container (train, evaluate, etc.)
