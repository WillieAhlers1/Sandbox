"""gml deploy — compile and deploy DAGs, pipeline YAMLs, and feature schemas."""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context

logger = logging.getLogger(__name__)


def deploy(
    name: str = typer.Argument(
        "", help="Pipeline name to deploy (directory name under pipelines/)"
    ),
    all_pipelines: bool = typer.Option(
        False, "--all", help="Deploy everything"
    ),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    dags_dir: Path = typer.Option(Path("dags"), "--dags-dir"),
    output_dir: Path = typer.Option(Path("compiled_pipelines"), "--out"),
    schema_dir: Path = typer.Option(
        Path("feature_schemas"), "--schema-dir"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be deployed"
    ),
) -> None:
    """
    Deploy compiled DAGs, pipeline YAMLs, and feature schemas.

    Runs 'gml compile' first if needed, then uploads artifacts to GCS/Composer.

    Examples:\n
        gml deploy churn_prediction\n
        gml deploy --all\n
        gml deploy --all --dry-run\n
    """
    if not name and not all_pipelines:
        err_console.print(
            "[red]Error:[/red] Provide a pipeline name or use --all."
        )
        raise typer.Exit(1)

    ctx = load_context()

    # Step 1: Compile first
    from gcp_ml_framework.cli.cmd_compile import compile_cmd

    try:
        compile_cmd(
            name=name,
            all_pipelines=all_pipelines,
            pipelines_dir=pipelines_dir,
            output_dir=output_dir,
            dags_dir=dags_dir,
        )
    except SystemExit as e:
        if e.code != 0:
            logger.error("Compilation failed — aborting deploy")
            raise typer.Exit(1)

    # Resolve artifact names to match
    match_names = {name} if name and not all_pipelines else set()

    # Step 2: Ensure Docker images referenced in pipeline YAMLs exist in AR
    if output_dir.exists():
        _ensure_images(
            output_dir, ctx, match_names, all_pipelines, dry_run
        )

    # Step 3: Upload DAG files to Composer bucket
    composer_path = ctx.composer_dags_path
    console.print(f"Using Composer DAGs path: {composer_path}")
    console.print(
        f"Looking for DAG files in: {dags_dir} {dags_dir.exists()}"
    )
    if composer_path and dags_dir.exists():
        _upload_dags(
            dags_dir, composer_path, ctx, match_names,
            all_pipelines, dry_run,
        )

    # Step 4: Upload compiled pipeline YAMLs to GCS
    if output_dir.exists():
        _upload_pipeline_yamls(
            output_dir, ctx, match_names, all_pipelines, dry_run
        )

    # Step 5: Deploy feature schemas (only with --all)
    if all_pipelines and schema_dir.exists():
        _deploy_features(schema_dir, ctx, dry_run)

    console.print("[green]Deploy complete.[/green]")


def _ensure_images(
    output_dir: Path,
    ctx,
    match_names: set[str],
    all_pipelines: bool,
    dry_run: bool,
) -> None:
    """Ensure Docker images referenced in compiled pipeline YAMLs exist in AR.

    Scans YAML files for image URIs matching the AR host. If a tag doesn't
    exist, finds the same image with any branch-matching tag and re-tags it.
    """
    import re

    from gcp_ml_framework.utils.ar import ensure_image_tag

    ar_prefix = (
        f"{ctx.artifact_registry_host}/{ctx.gcp_project}/"
    )
    image_pattern = re.compile(
        re.escape(ar_prefix) + r"[a-z0-9-]+/[a-z0-9-]+:[a-z0-9._-]+"
    )

    seen: set[str] = set()
    for yaml_file in output_dir.glob("*.yaml"):
        if (
            not all_pipelines
            and match_names
            and not any(n in yaml_file.name for n in match_names)
        ):
            continue
        content = yaml_file.read_text()
        for match in image_pattern.findall(content):
            if match not in seen:
                seen.add(match)

    if not seen:
        return

    for image_uri in sorted(seen):
        if dry_run:
            console.print(
                f"[dim](dry-run) would verify image:[/dim] {image_uri}"
            )
            continue
        ok = ensure_image_tag(image_uri, project=ctx.gcp_project)
        if ok:
            console.print(f"[green]Image verified:[/green] {image_uri}")
        else:
            err_console.print(
                f"[red]Error:[/red] Image not found: {image_uri}\n"
                "  Run `gml build` to build and push images."
            )
            raise typer.Exit(1)


def _upload_dags(
    dags_dir: Path,
    composer_path: str,
    ctx,
    match_names: set[str],
    all_pipelines: bool,
    dry_run: bool,
) -> None:
    """Upload DAG files to the Composer GCS bucket."""
    from gcp_ml_framework.utils.gcs import upload_file

    for dag_file in dags_dir.glob("*.py"):
        if (
            not all_pipelines
            and match_names
            and not any(n in dag_file.name for n in match_names)
        ):
            continue
        gcs_dest = f"{composer_path}/{dag_file.name}"
        if dry_run:
            console.print(
                f"[dim](dry-run) would upload:[/dim] {dag_file} "
                f"\u2192 {gcs_dest}"
            )
        else:
            upload_file(
                local_path=dag_file,
                gcs_uri=gcs_dest,
                project=ctx.gcp_project,
            )
            console.print(f"[green]Uploaded DAG:[/green] {gcs_dest}")


def _upload_pipeline_yamls(
    output_dir: Path,
    ctx,
    match_names: set[str],
    all_pipelines: bool,
    dry_run: bool,
) -> None:
    """Upload compiled pipeline YAMLs to GCS."""
    from gcp_ml_framework.utils.gcs import upload_file

    for yaml_file in output_dir.glob("*.yaml"):
        if (
            not all_pipelines
            and match_names
            and not any(n in yaml_file.name for n in match_names)
        ):
            continue
        gcs_dest = ctx.naming.gcs_path(
            "pipelines", yaml_file.stem, "pipeline.yaml"
        )
        if dry_run:
            console.print(
                f"[dim](dry-run) would upload:[/dim] {yaml_file} "
                f"\u2192 {gcs_dest}"
            )
        else:
            upload_file(
                local_path=yaml_file,
                gcs_uri=gcs_dest,
                project=ctx.gcp_project,
            )
            console.print(
                f"[green]Uploaded pipeline YAML:[/green] {gcs_dest}"
            )


def _deploy_features(schema_dir: Path, ctx, dry_run: bool) -> None:
    """Deploy feature schemas."""
    from gcp_ml_framework.feature_store.client import FeatureStoreClient
    from gcp_ml_framework.feature_store.schema import load_entity_schemas

    schemas = load_entity_schemas(schema_dir)
    if not schemas:
        return

    for entity_name, schema in schemas.items():
        if dry_run:
            console.print(
                f"[dim](dry-run) would deploy feature entity:[/dim] "
                f"{entity_name}"
            )
        else:
            try:
                client = FeatureStoreClient(ctx)
                client.ensure_entity(schema)
                console.print(
                    f"[green]Deployed feature entity:[/green] "
                    f"{entity_name}"
                )
            except Exception as e:
                err_console.print(
                    f"[yellow]Warning:[/yellow] Feature schema "
                    f"'{entity_name}' skipped: {e}"
                )
