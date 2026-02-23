"""gml teardown — delete ephemeral DEV resources for a branch namespace."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context

teardown_app = typer.Typer(help="Delete ephemeral DEV resources for a branch namespace.")


@teardown_app.command()
def teardown(
    branch: str = typer.Option(..., "--branch", "-b", help="Git branch whose resources to delete"),
    framework_yaml: Optional[Path] = typer.Option(None, "--config", "-c"),
    confirm: bool = typer.Option(False, "--confirm", help="Skip interactive confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="List resources that would be deleted"),
) -> None:
    """
    Delete all DEV GCP resources for the given branch namespace.

    Safe-guards:
    - Only deletes resources in the DEV environment (non-main, non-prod branches).
    - Never touches STAGE or PROD resources.
    - Requires --confirm or interactive Y/N prompt.

    Deleted resources:
    - GCS objects under gs://{bucket}/{branch}/
    - BigQuery dataset {team}_{project}_{branch_safe}
    - Vertex AI experiments and pipeline runs for the namespace
    - Feature Store feature views for the branch

    Example:
        gml teardown --branch feature/user-embeddings --confirm
    """
    from gcp_ml_framework.config import GitState, _resolve_git_state

    git_state = _resolve_git_state(branch)
    if git_state in (GitState.STAGING, GitState.PROD, GitState.PROD_EXP):
        err_console.print(
            f"[red]ERROR:[/red] Branch '{branch}' resolves to {git_state.value.upper()} — "
            "teardown is only allowed for DEV branches."
        )
        raise typer.Exit(1)

    ctx = load_context(framework_yaml=framework_yaml, branch=branch)

    console.print(f"\n[bold yellow]Teardown plan for branch:[/bold yellow] {branch!r}")
    console.print(f"  Namespace  : {ctx.namespace}")
    console.print(f"  GCP project: {ctx.gcp_project}")
    console.print(f"  GCS prefix : {ctx.gcs_prefix}")
    console.print(f"  BQ dataset : {ctx.bq_dataset}")
    console.print(f"  FS views   : {ctx.naming.feature_view_id('*', '*')}\n")

    if dry_run:
        console.print("[yellow](dry-run) No changes made.[/yellow]")
        return

    if not confirm:
        confirmed = typer.confirm(f"Delete ALL resources for namespace '{ctx.namespace}'?")
        if not confirmed:
            console.print("Aborted.")
            raise typer.Exit(0)

    from gcp_ml_framework.utils.gcs import delete_gcs_prefix
    from gcp_ml_framework.utils.bq import delete_bq_dataset

    # Delete GCS prefix
    console.print("Deleting GCS objects...")
    delete_gcs_prefix(prefix=ctx.gcs_prefix, project=ctx.gcp_project)
    console.print(f"  [green]Deleted:[/green] {ctx.gcs_prefix}")

    # Delete BQ dataset
    console.print("Deleting BigQuery dataset...")
    delete_bq_dataset(dataset=ctx.bq_dataset, project=ctx.gcp_project)
    console.print(f"  [green]Deleted:[/green] {ctx.bq_dataset}")

    console.print(f"\n[bold green]Teardown complete[/bold green] for namespace '{ctx.namespace}'.")
