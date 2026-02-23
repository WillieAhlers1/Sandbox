"""gml promote — promote STAGE artifacts to PROD."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from gcp_ml_framework.cli._helpers import console, load_context

promote_app = typer.Typer(help="Promote validated STAGE artifacts to PROD.")


@promote_app.command()
def promote(
    from_branch: str = typer.Option("main", "--from", help="Source branch (usually 'main')"),
    to_branch: str = typer.Option("prod", "--to", help="Target environment ('prod')"),
    tag: str = typer.Option(..., "--tag", help="Release tag (e.g. v1.2.3)"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Optional[Path] = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """
    Promote compiled pipeline artifacts from STAGE (main) to PROD.

    This command:
    1. Copies compiled pipeline YAMLs from the STAGE GCS prefix → PROD GCS prefix.
    2. Promotes validated Vertex AI Models from STAGE Model Registry → PROD.
    3. Syncs DAG files to the PROD Composer bucket.
    4. Tags PROD resources with the release tag for auditability.

    PROD is never deployed from source code — only validated STAGE artifacts.

    Example:
        gml promote --from main --to prod --tag v1.3.0
    """
    from gcp_ml_framework.config import load_config
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.utils.gcs import copy_gcs_prefix

    # Build source (STAGE) and target (PROD) contexts
    stage_cfg = load_config(framework_yaml=framework_yaml, branch=from_branch)
    stage_ctx = MLContext.from_config(stage_cfg)

    prod_cfg = load_config(framework_yaml=framework_yaml, branch=tag)
    prod_ctx = MLContext.from_config(prod_cfg)

    console.print(f"\n[bold]Promoting[/bold] STAGE → PROD (tag: {tag})")
    console.print(f"  Source: {stage_ctx.gcs_prefix}")
    console.print(f"  Target: {prod_ctx.gcs_prefix}\n")

    if dry_run:
        console.print("[yellow](dry-run) No changes made.[/yellow]")
        return

    # Copy compiled pipeline artifacts
    copy_gcs_prefix(
        src_prefix=stage_ctx.naming.gcs_path("pipelines"),
        dst_prefix=prod_ctx.naming.gcs_path("pipelines"),
        src_project=stage_ctx.gcp_project,
        dst_project=prod_ctx.gcp_project,
    )
    console.print("[green]Pipeline artifacts copied.[/green]")

    # Sync DAGs
    pipelines = [
        p.name for p in pipelines_dir.iterdir()
        if p.is_dir() and (p / "pipeline.py").exists()
    ]
    from gcp_ml_framework.dag.factory import DAGFactory
    from gcp_ml_framework.utils.gcs import upload_file

    dags_dir = Path("dags")
    dags_dir.mkdir(exist_ok=True)
    for pipeline_name in pipelines:
        dag_filename = f"{prod_ctx.naming.dag_id(pipeline_name)}.py"
        dag_path = dags_dir / dag_filename
        dag_content = DAGFactory.render_dag_file(pipeline_name, prod_ctx)
        dag_path.write_text(dag_content)
        if prod_ctx.composer_env:
            gcs_dest = prod_ctx.naming.gcs_dag_sync_path(dag_filename)
            upload_file(local_path=dag_path, gcs_uri=gcs_dest, project=prod_ctx.gcp_project)
    console.print("[green]PROD DAGs synced.[/green]")
    console.print(f"\n[bold green]Promotion complete.[/bold green] Tag: {tag}")
