"""EmailTask — send an email notification as a Composer task."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig
from gcp_ml_framework.dag.tasks.bq_query import _resolve_templates

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class EmailTask(BaseTask):
    """
    Send an email notification as a Composer task.

    Template variables in subject and body:
      {namespace}   — branch namespace
      {bq_dataset}  — branch-namespaced BQ dataset
      {run_date}    — converted to Airflow {{ ds }} macro
    """

    task_type: str = field(default="email", init=False)
    config: TaskConfig = field(default_factory=TaskConfig)

    to: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    cc: list[str] = field(default_factory=list)

    def resolve_subject(self, context: MLContext) -> str:
        return _resolve_templates(self.subject, context)

    def resolve_body(self, context: MLContext) -> str:
        return _resolve_templates(self.body, context)

    def validate(self, context: MLContext) -> list[str]:
        errors: list[str] = []
        if not self.to:
            errors.append("EmailTask requires at least one recipient in 'to'")
        if not self.subject.strip():
            errors.append("EmailTask requires a non-empty subject")
        return errors

    def as_airflow_operator(self, context: MLContext, dag: Any, task_id: str) -> Any:
        from airflow.operators.email import EmailOperator  # type: ignore[import]

        return EmailOperator(
            task_id=task_id,
            to=self.to,
            cc=self.cc or None,
            subject=self.resolve_subject(context),
            html_content=self.resolve_body(context),
            dag=dag,
        )
