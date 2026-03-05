"""gml context — show resolved namespace and resource map."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, load_context, print_kv_table

context_app = typer.Typer(help="Show context and resolved resource names.")


@context_app.command("show")
def show(
    framework_yaml: Path | None = typer.Option(None, "--config", "-c", help="Path to framework.yaml"),
    branch: str | None = typer.Option(None, "--branch", "-b", help="Override git branch"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Display the resolved namespace, GCP project, and all derived resource names
    for the current git branch (or --branch override).

    Example:
        gml context show
        gml context show --branch main
    """
    ctx = load_context(framework_yaml=framework_yaml, branch=branch)

    if json_output:
        import json
        typer.echo(json.dumps(ctx.summary(), indent=2))
        return

    console.print()
    console.print(f"[bold cyan]GCP ML Framework[/bold cyan] — context for branch [yellow]{ctx.raw_branch!r}[/yellow]")
    console.print()
    print_kv_table("Identity", {
        "team": ctx.naming.team,
        "project": ctx.naming.project,
        "branch (raw)": ctx.raw_branch,
        "branch (slug)": ctx.naming.branch,
        "git_state": ctx.git_state.value.upper(),
    })
    console.print()
    print_kv_table("GCP", {
        "project": ctx.gcp_project,
        "region": ctx.region,
        "composer_dags_path": str(ctx.composer_dags_path) if ctx.composer_dags_path else "(not configured)",
    })
    console.print()
    print_kv_table("Resource Names", {
        "namespace": ctx.namespace,
        "gcs_bucket": ctx.naming.gcs_bucket,
        "gcs_prefix": ctx.gcs_prefix,
        "bq_dataset": ctx.bq_dataset,
        "feature_store_id": ctx.feature_store_id,
        "dag_id pattern": ctx.naming.dag_id("{pipeline}"),
        "vertex_experiment pattern": ctx.naming.vertex_experiment("{pipeline}"),
        "secret_prefix": ctx.secret_prefix,
    })
    console.print()
