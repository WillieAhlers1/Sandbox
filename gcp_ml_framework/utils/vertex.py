"""Reusable Vertex AI deployment logic — extracted from deploy component."""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def run_deploy(
    *,
    project: str,
    region: str,
    model_display_name: str,
    endpoint_display_name: str,
    machine_type: str,
    min_replica_count: int,
    max_replica_count: int,
    traffic_split: dict[str, int],
    output_uri_path: str,
    # Monitoring (optional)
    enable_monitoring: bool = False,
    monitoring_alert_email: str = "",
    monitoring_log_sample_rate: float = 0.8,
    monitoring_monitor_interval: int = 3600,
    monitoring_skew_thresholds: dict[str, float] | None = None,
    monitoring_drift_thresholds: dict[str, float] | None = None,
) -> None:
    """Look up a registered model and deploy it to a Vertex AI Endpoint.

    The model must already be registered (via RegisterModel) — the serving
    container image is captured during registration and does not need to be
    provided here.
    """
    from google.cloud import aiplatform

    aiplatform.init(project=project, location=region)

    # Look up the registered model by display name
    existing_models = aiplatform.Model.list(
        filter=f'display_name="{model_display_name}"',
        project=project,
        location=region,
    )
    if not existing_models:
        raise ValueError(
            f"No registered model found with display_name='{model_display_name}'. "
            "Ensure RegisterModel runs before DeployModel."
        )

    model = existing_models[0]
    logger.info(f"Found registered model: {model.resource_name}")

    # Get or create endpoint
    existing = aiplatform.Endpoint.list(
        filter=f'display_name="{endpoint_display_name}"',
        project=project,
        location=region,
    )
    endpoint = existing[0] if existing else aiplatform.Endpoint.create(
        display_name=endpoint_display_name,
        project=project,
        location=region,
    )

    endpoint.deploy(
        model=model,
        machine_type=machine_type,
        min_replica_count=min_replica_count,
        max_replica_count=max_replica_count,
        traffic_split={"0": traffic_split.get("new", 100)},
    )
    logger.info("Deployed to endpoint %s", endpoint.resource_name)

    if output_uri_path:
        Path(output_uri_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_uri_path).write_text(endpoint.resource_name)

    # Model monitoring (optional)
    if enable_monitoring:
        try:
            create_kwargs: dict = {
                "display_name": f"{endpoint_display_name}-monitoring",
                "endpoint": endpoint,
                "logging_sampling_strategy": {
                    "random_sample_config": {
                        "sample_rate": monitoring_log_sample_rate,
                    },
                },
                "schedule_config": {
                    "monitor_interval": {
                        "seconds": monitoring_monitor_interval,
                    },
                },
            }
            if monitoring_alert_email:
                create_kwargs["alert_config"] = {
                    "email_alert_config": {
                        "user_emails": [monitoring_alert_email],
                    },
                }
            monitoring_job = aiplatform.ModelDeploymentMonitoringJob.create(
                **create_kwargs,
            )
            logger.info("Created monitoring job: %s", monitoring_job.resource_name)
        except Exception:
            logger.warning("Monitoring job creation failed (non-fatal)", exc_info=True)
