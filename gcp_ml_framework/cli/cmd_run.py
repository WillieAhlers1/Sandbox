"""gml run — run pipelines locally or trigger via Composer."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context
from gcp_ml_framework.context import MLContext


def _load_pipeline(pipeline_dir: Path):
    """Import a pipeline.py and return its `pipeline` object."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "_pipeline", pipeline_dir / "pipeline.py"
    )
    if spec is None or spec.loader is None:
        raise FileNotFoundError(
            f"No pipeline.py found in {pipeline_dir}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pipeline"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not hasattr(mod, "pipeline"):
        raise AttributeError(
            f"{pipeline_dir}/pipeline.py must define a `pipeline` variable"
        )
    return mod.pipeline


def run(
    pipeline_name: str = typer.Argument(
        "", help="Pipeline directory name under pipelines/"
    ),
    local: bool = typer.Option(
        False, "--local",
        help="Execute all steps in-process against real GCP dev resources",
    ),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    all_pipelines: bool = typer.Option(
        False, "--all", help="Run all pipelines in pipelines/"
    ),
    run_date: str = typer.Option(
        "", "--run-date",
        help="Override run_date (default: today). Only used with --local.",
    ),
) -> None:
    """
    Run a pipeline via Composer or execute locally.

    Defaults to triggering the deployed DAG in Composer.
    Use --local for in-process execution against real GCP dev resources.

    Examples:\n
        gml run training_pipeline\n
        gml run training_pipeline --local\n
        gml run --all --local\n
    """
    if not pipeline_name and not all_pipelines:
        err_console.print(
            "[red]Error:[/red] Provide a pipeline name or use --all."
        )
        raise typer.Exit(1)

    if local:
        _run_local(pipeline_name, pipelines_dir, run_date)
    else:
        _run_composer(pipeline_name, pipelines_dir, all_pipelines)


def composer_trigger_command(
    ctx: MLContext,
    pipeline_name: str,
) -> list[str]:
    """Construct the gcloud command to trigger a Composer DAG (pure, testable)."""
    dag_id = ctx.naming.dag_id(pipeline_name)
    return [
        "gcloud", "composer", "environments", "run",
        ctx.composer_environment_name,
        "--location", ctx.region,
        "--project", ctx.gcp_project,
        "dags", "trigger", "--", dag_id,
    ]


def _run_composer(
    pipeline_name: str,
    pipelines_dir: Path,
    all_pipelines: bool,
) -> None:
    """Trigger deployed DAG(s) in Composer."""
    import subprocess

    ctx = load_context()

    targets = (
        sorted(
            d.name for d in pipelines_dir.iterdir()
            if d.is_dir() and (d / "pipeline.py").exists()
        )
        if all_pipelines
        else [pipeline_name]
    )

    for name in targets:
        cmd = composer_trigger_command(ctx, name)
        dag_id = ctx.naming.dag_id(name)

        console.print(
            f"[bold]Triggering DAG:[/bold] {dag_id} "
            f"in {ctx.composer_environment_name}"
        )

        result = subprocess.run(cmd, check=False)

        if result.returncode != 0:
            err_console.print(
                f"[red]Error:[/red] Failed to trigger DAG '{dag_id}' "
                f"(exit {result.returncode}).\n"
                f"  Verify the DAG is deployed: gml deploy {name}"
            )
            raise typer.Exit(1)

        console.print(f"[green]Triggered:[/green] {dag_id}")


def _run_local(
    pipeline_name: str,
    pipelines_dir: Path,
    run_date: str,
) -> None:
    """Execute a pipeline locally in-process against real GCP dev resources."""
    from gcp_ml_framework.pipeline.local_runner import LocalRunner

    ctx = load_context()
    pipeline_dir = pipelines_dir / pipeline_name
    pipeline_def = _load_pipeline(pipeline_dir)

    console.print(
        f"[cyan]Running '{pipeline_name}' locally "
        f"({len(pipeline_def.steps)} steps)...[/cyan]"
    )

    runner = LocalRunner()
    runner.run(pipeline_def, ctx, run_date=run_date)

    console.print(
        f"[green]Local run complete:[/green] {pipeline_name}"
    )
