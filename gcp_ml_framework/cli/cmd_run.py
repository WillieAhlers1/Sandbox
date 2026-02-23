"""gml run — run pipelines locally or on Vertex AI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context

run_app = typer.Typer(help="Run pipelines locally or on Vertex AI.")


def _load_pipeline(pipeline_dir: Path):
    """Import a pipeline.py and return its `pipeline` object."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("_pipeline", pipeline_dir / "pipeline.py")
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"No pipeline.py found in {pipeline_dir}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pipeline"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not hasattr(mod, "pipeline"):
        raise AttributeError(f"{pipeline_dir}/pipeline.py must define a `pipeline` variable")
    return mod.pipeline


@run_app.command("local")
def run_local(
    pipeline_name: str = typer.Argument(..., help="Pipeline directory name under pipelines/"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Optional[Path] = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print execution plan without running"),
) -> None:
    """
    Run a pipeline locally using DuckDB/pandas stubs instead of GCP services.

    Useful for rapid iteration and unit testing without GCP access.

    Example:
        gml run local churn_prediction
        gml run local churn_prediction --dry-run
    """
    from gcp_ml_framework.pipeline.runner import LocalRunner

    pipeline_dir = pipelines_dir / pipeline_name
    ctx = load_context(
        framework_yaml=framework_yaml,
        pipeline_yaml=pipeline_dir / "config.yaml" if (pipeline_dir / "config.yaml").exists() else None,
    )
    pipeline_def = _load_pipeline(pipeline_dir)

    runner = LocalRunner(ctx)
    if dry_run:
        runner.print_plan(pipeline_def)
    else:
        console.print(f"[cyan]Running {pipeline_name!r} locally...[/cyan]")
        runner.run(pipeline_def)
        console.print("[green]Done.[/green]")


@run_app.command("vertex")
def run_vertex(
    pipeline_name: str = typer.Argument(..., help="Pipeline directory name under pipelines/"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Optional[Path] = typer.Option(None, "--config", "-c"),
    sync: bool = typer.Option(False, "--sync", help="Block until the pipeline run completes"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable KFP step caching"),
    all_pipelines: bool = typer.Option(False, "--all", help="Run all pipelines in pipelines/"),
) -> None:
    """
    Compile and submit a pipeline to Vertex AI Pipelines.

    Example:
        gml run vertex churn_prediction --sync
        gml run vertex --all
    """
    from gcp_ml_framework.pipeline.compiler import PipelineCompiler
    from gcp_ml_framework.pipeline.runner import VertexRunner

    ctx = load_context(framework_yaml=framework_yaml)

    targets = (
        [p.name for p in pipelines_dir.iterdir() if p.is_dir() and (p / "pipeline.py").exists()]
        if all_pipelines
        else [pipeline_name]
    )

    for name in targets:
        pipeline_dir = pipelines_dir / name
        pipeline_def = _load_pipeline(pipeline_dir)
        compiler = PipelineCompiler()
        compiled_path = compiler.compile(pipeline_def, ctx)
        runner = VertexRunner(ctx)
        job = runner.submit(
            compiled_path=compiled_path,
            pipeline_name=name,
            enable_caching=not no_cache,
            sync=sync,
        )
        console.print(f"[green]Submitted:[/green] {job.resource_name}")


@run_app.command("compile")
def run_compile(
    pipeline_name: str = typer.Argument("", help="Pipeline to compile. Omit for --all."),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Optional[Path] = typer.Option(None, "--config", "-c"),
    output_dir: Path = typer.Option(Path("compiled_pipelines"), "--out"),
    all_pipelines: bool = typer.Option(False, "--all"),
) -> None:
    """
    Compile pipeline(s) to KFP YAML without submitting. Used in CI for validation.

    Example:
        gml run compile --all
        gml run compile churn_prediction --out /tmp/compiled
    """
    from gcp_ml_framework.pipeline.compiler import PipelineCompiler

    ctx = load_context(framework_yaml=framework_yaml)
    targets = (
        [p.name for p in pipelines_dir.iterdir() if p.is_dir() and (p / "pipeline.py").exists()]
        if all_pipelines or not pipeline_name
        else [pipeline_name]
    )

    compiler = PipelineCompiler(output_dir=output_dir)
    for name in targets:
        pipeline_def = _load_pipeline(pipelines_dir / name)
        path = compiler.compile(pipeline_def, ctx)
        console.print(f"[green]Compiled:[/green] {path}")
