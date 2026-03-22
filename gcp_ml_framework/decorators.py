"""Decorators: @task (Airflow operators) and @ml_task (Vertex AI)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar, overload

from gcp_ml_framework.types import TaskType

if TYPE_CHECKING:
    from gcp_ml_framework.components.base import BaseComponent

_C = TypeVar("_C")


def task(cls: _C) -> _C:
    """Mark a component class as an Airflow operator task.

    Components decorated with @task are compiled to native Airflow operators
    (e.g. BigQueryInsertJobOperator, EmailOperator) rather than Vertex AI
    container components.

    Usage:
        @task
        class BQQuery(BaseComponent):
            ...
    """
    cls.task_type = TaskType.TASK
    return cls


@overload
def ml_task(_cls: _C) -> _C: ...

@overload
def ml_task(
    _cls: None = None,
    *,
    machine_type: str | None = None,
    accelerator_type: str | None = None,
    accelerator_count: int | None = None,
) -> Callable[[_C], _C]: ...

def ml_task(
    _cls: _C | None = None,
    *,
    machine_type: str | None = None,
    accelerator_type: str | None = None,
    accelerator_count: int | None = None,
) -> _C | Callable[[_C], _C]:
    """Mark a component class as a Vertex AI container task.

    Optionally override default resource settings. Can be used with or without
    arguments:

        @ml_task
        class TrainModel(BaseComponent): ...

        @ml_task(machine_type="a2-highgpu-1g", accelerator_type="NVIDIA_TESLA_A100")
        class TrainLargeModel(BaseComponent): ...
    """

    def decorator(cls: _C) -> _C:
        cls.task_type = TaskType.ML_TASK
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
