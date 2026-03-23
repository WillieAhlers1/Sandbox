"""DBTRun — execute dbt models as an Airflow task."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.decorators import task

if TYPE_CHECKING:
    from pathlib import Path

    from gcp_ml_framework.context import MLContext


@task
class DBTRun(BaseComponent):
    """Run dbt models inside an Airflow DAG.

    Rendered as a BashOperator with ``dbt run`` command.
    Fields map to dbt CLI flags.

    Example::

        DBTRun(
            project_dir="/dbt",
            target="dev",
            models="marts.finance",
        )
    """

    project_dir: str = "/dbt"
    target: str = "dev"
    models: str = ""
    dbt_vars: str = ""
    component_name: str = "dbt_run"

    def render_operator(
        self,
        context: MLContext,
        pipeline_dir: Path | None = None,
    ) -> tuple[str, set[str]]:
        """Return (operator_code, imports) for Airflow DAG generation."""
        imports = {"from airflow.operators.bash import BashOperator"}

        cmd_parts = [f"cd {self.project_dir} && dbt run --target {self.target}"]
        if self.models:
            cmd_parts.append(f"--models {self.models}")
        if self.dbt_vars:
            cmd_parts.append(f"--vars '{self.dbt_vars}'")
        cmd = " ".join(cmd_parts)

        code = f'''BashOperator(
        task_id="{{{{ task_id }}}}",
        bash_command="{cmd}",
    )'''

        return code, imports

    def execute(self) -> None:
        """Execute dbt run locally (for --local mode)."""
        import subprocess

        from loguru import logger

        cmd = [
            "dbt",
            "run",
            "--project-dir",
            self.project_dir,
            "--target",
            self.target,
        ]
        if self.models:
            cmd.extend(["--models", self.models])
        if self.dbt_vars:
            cmd.extend(["--vars", self.dbt_vars])
        logger.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    DBTRun.cli()
