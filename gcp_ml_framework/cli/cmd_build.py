"""gml build — build Docker images via Google Cloud Build."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.naming import _slugify


def build(
    name: str = typer.Argument("", help="Pipeline name to build"),
    all_pipelines: bool = typer.Option(False, "--all", help="Build all pipelines"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    timeout: int = typer.Option(1200, "--timeout", help="Build timeout in seconds"),
) -> None:
    """Build Docker images via Google Cloud Build."""
    if not name and not all_pipelines:
        err_console.print("[red]Error:[/red] Provide a pipeline name or use --all.")
        raise typer.Exit(1)

    ctx = load_context()

    if all_pipelines:
        names = sorted(
            d.name for d in pipelines_dir.iterdir() if d.is_dir() and (d / "pipeline.py").exists()
        )
    else:
        names = [name]

    for pipeline_name in names:
        _submit_build(ctx, pipeline_name, timeout)


def build_command(
    ctx: MLContext,
    pipeline_name: str,
    timeout: int = 1200,
) -> list[str]:
    """Construct the gcloud builds submit command (pure, testable)."""
    tag = ctx.naming.image_tag(pipeline_name)
    ar_repo = ctx.naming.artifact_registry_repo(ctx.artifact_registry_host, ctx.gcp_project)
    pipeline_slug = _slugify(pipeline_name)

    substitutions = (
        f"_TAG={tag},_PIPELINE={pipeline_slug},_PIPELINE_DIR={pipeline_name},_AR_REPO={ar_repo}"
    )

    cmd = [
        "gcloud",
        "builds",
        "submit",
        "--config",
        "cloudbuild.yaml",
        "--project",
        ctx.gcp_project,
        f"--timeout={timeout}s",
        f"--substitutions={substitutions}",
    ]

    # Use the pipeline SA for Cloud Build (sandbox environments
    # where the default Cloud Build SA lacks AR push permissions).
    sa_email = ctx.pipeline_service_account
    sa_resource = f"projects/{ctx.gcp_project}/serviceAccounts/{sa_email}"
    cmd.extend(["--service-account", sa_resource])

    cmd.append(".")
    return cmd


def _submit_build(ctx: MLContext, pipeline_name: str, timeout: int) -> None:
    """Submit a Cloud Build job for one pipeline."""
    import subprocess

    cmd = build_command(ctx, pipeline_name, timeout)
    pipeline_slug = _slugify(pipeline_name)
    ar_repo = ctx.naming.artifact_registry_repo(ctx.artifact_registry_host, ctx.gcp_project)
    tag = ctx.naming.image_tag(pipeline_name)

    console.print(f"[bold]Building:[/bold] {ar_repo}/{pipeline_slug}:{tag}")
    result = subprocess.run(cmd, check=False)

    if result.returncode != 0:
        err_console.print(
            f"[red]Error:[/red] Cloud Build failed (exit {result.returncode}).\n"
            "  Check logs: https://console.cloud.google.com/cloud-build/builds"
        )
        raise typer.Exit(1)

    console.print(f"[green]Built:[/green] {ar_repo}/{pipeline_slug}:{tag}")
