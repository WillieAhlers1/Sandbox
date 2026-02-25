"""gml deploy — deploy DAGs and Feature Store schemas."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, load_context

deploy_app = typer.Typer(help="Deploy DAGs, feature schemas, and infrastructure.")


@deploy_app.command("dags")
def deploy_dags(
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    dags_dir: Path = typer.Option(Path("dags"), "--dags-dir"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """
    Generate Airflow DAG files and sync them to the Composer GCS bucket.

    One DAG file is created per pipeline. The DAG ID encodes the branch namespace.

    Example:
        gml deploy dags
        gml deploy dags --dry-run
    """
    from gcp_ml_framework.dag.factory import DAGFactory
    from gcp_ml_framework.utils.gcs import upload_file

    ctx = load_context(framework_yaml=framework_yaml)
    dags_dir.mkdir(exist_ok=True)

    pipelines = [
        p for p in pipelines_dir.iterdir()
        if p.is_dir() and (p / "pipeline.py").exists()
    ]
    if not pipelines:
        console.print("[yellow]No pipelines found.[/yellow]")
        return

    for pipeline_dir in pipelines:
        pipeline_name = pipeline_dir.name
        dag_filename = f"{ctx.naming.dag_id(pipeline_name)}.py"
        dag_path = dags_dir / dag_filename
        dag_content = DAGFactory.render_dag_file(pipeline_name, ctx)
        dag_path.write_text(dag_content)
        console.print(f"[dim]Generated:[/dim] {dag_path}")

        if not dry_run and ctx.composer_env:
            gcs_dest = ctx.naming.gcs_dag_sync_path(dag_filename)
            upload_file(local_path=dag_path, gcs_uri=gcs_dest, project=ctx.gcp_project)
            console.print(f"[green]Synced:[/green] {gcs_dest}")
        elif dry_run:
            console.print(f"[dim](dry-run) would sync to:[/dim] {ctx.naming.gcs_dag_sync_path(dag_filename)}")


@deploy_app.command("features")
def deploy_features(
    schema_dir: Path = typer.Option(Path("feature_schemas"), "--schema-dir"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
    entities: list[str] | None = typer.Argument(None, help="Entity names to deploy. Deploys all if omitted."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """
    Upsert Feature Store entity types and feature views from YAML schemas.

    Example:
        gml deploy features          # deploy all schemas
        gml deploy features user item
    """
    from gcp_ml_framework.feature_store.client import FeatureStoreClient
    from gcp_ml_framework.feature_store.schema import load_entity_schemas

    ctx = load_context(framework_yaml=framework_yaml)
    schemas = load_entity_schemas(schema_dir)

    if entities:
        schemas = {k: v for k, v in schemas.items() if k in entities}

    if not schemas:
        console.print("[yellow]No feature schemas found.[/yellow]")
        return

    for entity_name, schema in schemas.items():
        console.print(f"[cyan]Deploying entity:[/cyan] {entity_name}")
        if not dry_run:
            client = FeatureStoreClient(ctx)
            client.ensure_entity(schema)
            console.print(f"[green]  OK:[/green] {entity_name}")
        else:
            console.print(f"[dim]  (dry-run) would upsert entity:[/dim] {entity_name}")
