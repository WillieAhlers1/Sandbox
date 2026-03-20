"""
DAG runners — Composer triggering.

ComposerRunner: triggers an already-deployed DAG on Cloud Composer via the
Airflow REST API.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


class ComposerRunner:
    """
    Trigger an already-deployed DAG on Cloud Composer via the Airflow REST API.

    Usage:
        runner = ComposerRunner(context)
        result = runner.trigger_dag("sales_analytics", run_date="2026-03-01")
    """

    def __init__(self, context: MLContext) -> None:
        self._ctx = context
        self._airflow_uri: str | None = None

    def resolve_dag_id(self, pipeline_name: str) -> str:
        """Derive the Composer DAG ID from the pipeline name and context."""
        return self._ctx.naming.dag_id(pipeline_name)

    def _get_airflow_uri(self) -> str:
        """Discover the Airflow webserver URI from the Composer environment."""
        if self._airflow_uri:
            return self._airflow_uri

        import subprocess

        env_name = self._ctx.composer_environment_name
        result = subprocess.run(
            [
                "gcloud",
                "composer",
                "environments",
                "describe",
                env_name,
                "--location",
                self._ctx.region,
                "--project",
                self._ctx.gcp_project,
                "--format",
                "value(config.airflowUri)",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self._airflow_uri = result.stdout.strip()
        return self._airflow_uri

    def _build_trigger_url(self, dag_id: str) -> str:
        """Build the Airflow REST API URL for triggering a DAG run."""
        base = self._get_airflow_uri()
        return f"{base}/api/v1/dags/{dag_id}/dagRuns"

    def _get_auth_headers(self) -> dict[str, str]:
        """Get Bearer token headers for the Airflow REST API.

        Uses Application Default Credentials (ADC) — works with user creds,
        service accounts, and Workload Identity.
        """
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return {"Authorization": f"Bearer {credentials.token}"}

    def _trigger_dag_run(self, dag_id: str, logical_date: str) -> dict[str, Any]:
        """Trigger a DAG run via the Airflow Stable REST API.

        POST /api/v1/dags/{dag_id}/dagRuns with a logical_date payload.
        Returns the parsed JSON response from Airflow.
        """
        import requests

        url = self._build_trigger_url(dag_id)
        headers = {**self._get_auth_headers(), "Content-Type": "application/json"}
        payload = {"logical_date": f"{logical_date}T00:00:00+00:00"}

        resp = requests.post(url, json=payload, headers=headers, timeout=120)

        if resp.status_code == 409:
            # DAG run already exists for this logical_date — treat as success
            logger.info(f"DAG run already exists for {logical_date} (409 Conflict)")
            return {
                "dag_run_id": f"manual__{logical_date}",
                "state": "queued",
                "conflict": True,
            }

        if not resp.ok:
            raise RuntimeError(
                f"Failed to trigger DAG '{dag_id}': {resp.status_code} {resp.text}"
            )

        return resp.json()

    def unpause_dag(self, dag_id: str) -> None:
        """Unpause a DAG via the Airflow Stable REST API.

        PATCH /api/v1/dags/{dag_id} with is_paused=false.
        Best-effort — a failure here should not block the trigger.
        """
        import requests

        try:
            base = self._get_airflow_uri()
            url = f"{base}/api/v1/dags/{dag_id}"
            headers = {**self._get_auth_headers(), "Content-Type": "application/json"}
            resp = requests.patch(
                url, json={"is_paused": False}, headers=headers, timeout=30
            )
            if resp.ok:
                logger.info(f"DAG '{dag_id}' unpaused")
            else:
                logger.info(f"Warning: unpause returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.info(f"Warning: could not unpause DAG '{dag_id}': {e}")

    def trigger_dag(self, pipeline_name: str, run_date: str = "") -> dict[str, Any]:
        """Trigger a DAG run on Composer. Returns the Airflow API response."""
        run_date = run_date or datetime.date.today().isoformat()
        dag_id = self.resolve_dag_id(pipeline_name)

        logger.info(f"Triggering DAG '{dag_id}' for date {run_date}...")
        result = self._trigger_dag_run(dag_id, run_date)
        logger.info(f"DAG run triggered: {result.get('dag_run_id', 'unknown')}")
        logger.info(f"State: {result.get('state', 'unknown')}")
        return result
