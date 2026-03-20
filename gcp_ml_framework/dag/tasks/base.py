"""BaseTask — abstract base class for all DAG task definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pydantic import BaseModel, ConfigDict, Field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


class TaskConfig(BaseModel):
    """Per-task Airflow configuration."""

    retries: int = 1
    retry_delay_minutes: int = 5
    timeout_hours: int = 1
    email_on_failure: bool = True
    pool: str | None = None
    priority_weight: int = 1


# Change: Migrate dataclasses to Pydantic BaseModel
class BaseTask(BaseModel, ABC):
    """
    Abstract base for all DAG task definitions.

    Subclasses define a task that maps to an Airflow operator.
    The task carries configuration, not execution logic.
    """

    task_type: str = ""
    config: TaskConfig = Field(default_factory=TaskConfig)

    @abstractmethod
    def as_airflow_operator(self, context: MLContext, dag: Any, task_id: str) -> Any:
        """Return an Airflow operator instance for this task."""
        ...

    def validate(self, context: MLContext) -> list[str]:
        """Validate task configuration. Return list of error messages."""
        return []
