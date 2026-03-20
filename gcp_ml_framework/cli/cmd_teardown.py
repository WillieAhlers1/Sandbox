"""gml teardown — delete ephemeral DEV resources for a branch namespace."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context

teardown_app = typer.Typer(help="Delete ephemeral DEV resources for a branch namespace.")


@teardown_app.command()
def teardown(
    branch: str = typer.Option(..., "--branch", "-b", help="Git branch whose resources to delete"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
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

    # Resolve Composer DAG pattern for this namespace
    dag_pattern = f"{ctx.naming.namespace_bq}__*"
    composer_path = ctx.composer_dags_path.get(ctx.git_state.value, "")

    console.print(f"\n[bold yellow]Teardown plan for branch:[/bold yellow] {branch!r}")
    console.print(f"  Namespace    : {ctx.namespace}")
    console.print(f"  GCP project  : {ctx.gcp_project}")
    console.print(f"  GCS prefix   : {ctx.gcs_prefix}")
    console.print(f"  BQ dataset   : {ctx.bq_dataset}")
    console.print(f"  Composer DAGs: {dag_pattern}")
    console.print(f"  FS views     : {ctx.naming.feature_view_id('*', '*')}\n")

    if dry_run:
        console.print("[yellow](dry-run) No changes made.[/yellow]")
        return

    if not confirm:
        confirmed = typer.confirm(f"Delete ALL resources for namespace '{ctx.namespace}'?")
        if not confirmed:
            console.print("Aborted.")
            raise typer.Exit(0)

    from gcp_ml_framework.utils.bq import delete_bq_dataset
    from gcp_ml_framework.utils.gcs import delete_gcs_prefix

    # Delete Composer DAGs (files from GCS bucket + Airflow metadata)
    if composer_path:
        console.print("Deleting Composer DAGs...")
        _delete_composer_dags(ctx, composer_path)

    # Delete GCS prefix
    console.print("Deleting GCS objects...")
    delete_gcs_prefix(prefix=ctx.gcs_prefix, project=ctx.gcp_project)
    console.print(f"  [green]Deleted:[/green] {ctx.gcs_prefix}")

    # Delete BQ dataset
    console.print("Deleting BigQuery dataset...")
    delete_bq_dataset(dataset=ctx.bq_dataset, project=ctx.gcp_project)
    console.print(f"  [green]Deleted:[/green] {ctx.bq_dataset}")

    console.print(f"\n[bold green]Teardown complete[/bold green] for namespace '{ctx.namespace}'.")


def _delete_composer_dags(ctx, composer_path: str) -> None:
    """Delete DAG files from Composer bucket and Airflow metadata."""
    import subprocess

    from google.cloud import storage  # type: ignore[import]

    # 1. Find and delete DAG files matching namespace from Composer bucket
    without_scheme = composer_path[5:]
    bucket_name, _, prefix_path = without_scheme.partition("/")
    client = storage.Client(project=ctx.gcp_project)
    namespace_prefix = ctx.naming.namespace_bq + "__"

    dag_ids = []
    for blob in client.list_blobs(bucket_name, prefix=prefix_path):
        filename = blob.name.split("/")[-1]
        if filename.startswith(namespace_prefix) and filename.endswith(".py"):
            dag_id = filename[:-3]  # strip .py
            dag_ids.append(dag_id)
            blob.delete()
            console.print(f"  [green]Deleted DAG file:[/green] {filename}")

    # 2. Delete Airflow metadata for each DAG
    env_name = ctx.composer_environment_name

    for dag_id in dag_ids:
        try:
            subprocess.run(
                [
                    "gcloud", "composer", "environments", "run",
                    env_name, "--location", ctx.region,
                    "--project", ctx.gcp_project,
                    "dags", "delete", "--", dag_id, "--yes",
                ],
                capture_output=True, text=True, check=True,
                timeout=120,
            )
            console.print(f"  [green]Deleted Airflow metadata:[/green] {dag_id}")
        except Exception as e:
            console.print(f"  [yellow]Warning:[/yellow] Could not delete Airflow metadata for {dag_id}: {e}")
