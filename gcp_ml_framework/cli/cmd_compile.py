"""gml compile — compile pipelines to deployable artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context, load_pipeline


def compile_cmd(
    name: str = typer.Argument(
        "", help="Pipeline name to compile (directory name under pipelines/)"
    ),
    all_pipelines: bool = typer.Option(False, "--all", help="Compile all pipelines"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    output_dir: Path = typer.Option(
        Path("compiled_pipelines"), "--out", help="Output dir for compiled YAML"
    ),
    dags_dir: Path = typer.Option(
        Path("dags"), "--dags-dir", help="Output dir for generated DAG files"
    ),
) -> None:
    """
    Compile pipeline(s) to KFP YAML and Airflow DAG files.

    Examples:\n
        gml compile churn_prediction\n
        gml compile --all\n
    """
    if not name and not all_pipelines:
        err_console.print("[red]Error:[/red] Provide a pipeline name or use --all.")
        raise typer.Exit(1)

    ctx = load_context()

    targets = _discover_targets(pipelines_dir, name, all_pipelines)
    if not targets:
        err_console.print("[yellow]No pipelines found.[/yellow]")
        raise typer.Exit(1)

    for pipeline_name in targets:
        pipeline_dir = pipelines_dir / pipeline_name
        if not (pipeline_dir / "pipeline.py").exists():
            err_console.print(f"[red]Error:[/red] {pipeline_name}/ has no pipeline.py.")
            raise typer.Exit(1)

        _compile_pipeline(pipeline_name, pipeline_dir, ctx, output_dir, dags_dir)


def _discover_targets(pipelines_dir: Path, name: str, all_pipelines: bool) -> list[str]:
    """Return list of pipeline directory names to compile."""
    if all_pipelines:
        return [
            p.name for p in pipelines_dir.iterdir() if p.is_dir() and (p / "pipeline.py").exists()
        ]
    return [name]


def _compile_pipeline(
    pipeline_name: str,
    pipeline_dir: Path,
    ctx,
    output_dir: Path,
    dags_dir: Path,
) -> None:
    """Compile a pipeline.py via SmartCompiler."""
    from gcp_ml_framework.pipeline.smart_compiler import SmartCompiler

    pipeline_def = load_pipeline(pipeline_dir)
    compiler = SmartCompiler(output_dir=output_dir, dags_dir=dags_dir)
    result = compiler.compile(pipeline_def, ctx, pipeline_dir=pipeline_dir)

    for yaml_path in result.yaml_paths:
        console.print(f"[green]Compiled KFP YAML:[/green] {yaml_path}")
    console.print(f"[green]Generated DAG:[/green] {result.dag_path}")
