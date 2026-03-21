"""Email — email notification as a unified component.

Absorbs EmailTask logic into the component system. Marked as @task so the
SmartCompiler renders it as a native Airflow EmailOperator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger
from pydantic import Field, model_validator

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from pathlib import Path

    from gcp_ml_framework.context import MLContext


@task
class Email(BaseComponent):
    """Send an email notification.

    Template variables in subject and body:
      {namespace}   — branch namespace
      {bq_dataset}  — branch-namespaced BQ dataset
      {run_date}    — converted to Airflow {{ ds }} macro at runtime
    """

    to: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    cc: list[str] = Field(default_factory=list)
    component_name: str = "email"

    @model_validator(mode="after")
    def _check_recipients(self) -> Email:
        if not self.to:
            raise ValueError("Email requires at least one recipient in 'to'")
        return self

    def resolve_subject(self, context: MLContext) -> str:
        from gcp_ml_framework.components.operators.bq_query import _resolve_templates

        return _resolve_templates(self.subject, context)

    def resolve_body(self, context: MLContext) -> str:
        from gcp_ml_framework.components.operators.bq_query import _resolve_templates

        return _resolve_templates(self.body, context)

    def execute(self) -> None:
        """Log warning — no SMTP in containers."""
        logger.warning(
            f"Email.execute() called in container context — skipping send. "
            f"To: {self.to}, Subject: {self.subject}"
        )

    def render_operator(
        self, context: MLContext, pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation."""
        imports = {
            "from airflow.operators.email import EmailOperator",
        }

        resolved_subject = self.resolve_subject(context)
        resolved_body = self.resolve_body(context)

        code = f"""EmailOperator(
        task_id="{{{{ task_id }}}}",
        to={self.to!r},
        cc={self.cc!r} if {bool(self.cc)} else None,
        subject="{resolved_subject}",
        html_content='''{resolved_body}''',
    )"""

        return code, imports
