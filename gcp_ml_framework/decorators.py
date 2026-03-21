"""Decorators: @task (Airflow operators) and @ml_task (Vertex AI)."""

from __future__ import annotations

from enum import StrEnum


class TaskType(StrEnum):
    """Discriminator for how a component is compiled."""

    TASK = "task"        # Airflow operator (BQ, email, etc.)
    ML_TASK = "ml_task"  # Vertex AI container (train, evaluate, etc.)


def task(cls):
    """Mark a component class as an Airflow operator task.

    Components decorated with @task are compiled to native Airflow operators
    (e.g. BigQueryInsertJobOperator, EmailOperator) rather than Vertex AI
    container components.

    Usage:
        @task
        class BQQuery(BaseComponent):
            ...
    """
    cls._task_type = TaskType.TASK
    return cls


def ml_task(
    _cls=None,
    *,
    machine_type: str | None = None,
    accelerator_type: str | None = None,
    accelerator_count: int | None = None,
):
    """Mark a component class as a Vertex AI container task.

    Optionally override default resource settings. Can be used with or without
    arguments:

        @ml_task
        class TrainModel(BaseComponent): ...

        @ml_task(machine_type="a2-highgpu-1g", accelerator_type="NVIDIA_TESLA_A100")
        class TrainLargeModel(BaseComponent): ...
    """

    def decorator(cls):
        cls._task_type = TaskType.ML_TASK
        needs_rebuild = False
        if machine_type is not None:
            cls.model_fields["machine_type"].default = machine_type
            needs_rebuild = True
        if accelerator_type is not None:
            cls.model_fields["accelerator_type"].default = accelerator_type
            needs_rebuild = True
        if accelerator_count is not None:
            cls.model_fields["accelerator_count"].default = accelerator_count
            needs_rebuild = True
        if needs_rebuild:
            cls.model_rebuild(force=True)
        return cls

    if _cls is not None:
        return decorator(_cls)
    return decorator
