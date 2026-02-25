"""gml run — run pipelines locally, on Vertex AI, or compile only."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context


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


def run(
    pipeline_name: str = typer.Argument("", help="Pipeline directory name under pipelines/"),
    local: bool = typer.Option(False, "--local", help="Run locally using DuckDB/pandas stubs"),
    vertex: bool = typer.Option(False, "--vertex", help="Compile and submit to Vertex AI Pipelines"),
    compile_only: bool = typer.Option(
        False, "--compile-only", help="Compile to KFP YAML without submitting (for CI)"
    ),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print execution plan without running"),
    sync: bool = typer.Option(False, "--sync", help="Block until the Vertex pipeline run completes"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable KFP step caching"),
    all_pipelines: bool = typer.Option(False, "--all", help="Run all pipelines in pipelines/"),
    output_dir: Path = typer.Option(
        Path("compiled_pipelines"), "--out", help="Output dir for compiled YAML"
    ),
) -> None:
    """
    Run a pipeline locally, on Vertex AI, or compile to YAML.

    Defaults to --local if no mode flag is given.

    Examples:\n
        gml run example_churn --local\n
        gml run example_churn --local --dry-run\n
        gml run example_churn --vertex --sync\n
        gml run --vertex --all\n
        gml run --compile-only --all\n
        gml run example_churn --compile-only --out /tmp/compiled\n
    """
    # Validate mutually exclusive flags
    mode_count = sum([local, vertex, compile_only])
    if mode_count > 1:
        err_console.print(
            "[red]Error:[/red] --local, --vertex, and --compile-only are mutually exclusive."
        )
        raise typer.Exit(1)

    # Default to --local if no flag given
    if mode_count == 0:
        local = True

    # Validate pipeline_name is given unless --all is used
    if not pipeline_name and not all_pipelines:
        err_console.print("[red]Error:[/red] Provide a pipeline name or use --all.")
        raise typer.Exit(1)

    if local:
        _run_local(pipeline_name, pipelines_dir, framework_yaml, dry_run)
    elif vertex:
        _run_vertex(pipeline_name, pipelines_dir, framework_yaml, sync, no_cache, all_pipelines)
    elif compile_only:
        _run_compile(pipeline_name, pipelines_dir, framework_yaml, output_dir, all_pipelines)


def _run_local(
    pipeline_name: str,
    pipelines_dir: Path,
    framework_yaml: Path | None,
    dry_run: bool,
) -> None:
    """Run a pipeline locally using DuckDB/pandas stubs."""
    from gcp_ml_framework.pipeline.runner import LocalRunner

    pipeline_dir = pipelines_dir / pipeline_name
    ctx = load_context(
        framework_yaml=framework_yaml,
        pipeline_yaml=pipeline_dir / "config.yaml" if (pipeline_dir / "config.yaml").exists() else None,
    )
    pipeline_def = _load_pipeline(pipeline_dir)

    seeds_dir = pipeline_dir / "seeds"
    runner = LocalRunner(ctx, seeds_dir=seeds_dir if seeds_dir.exists() else None)
    if dry_run:
        runner.print_plan(pipeline_def)
    else:
        console.print(f"[cyan]Running {pipeline_name!r} locally...[/cyan]")
        runner.run(pipeline_def)
        console.print("[green]Done.[/green]")


def _run_vertex(
    pipeline_name: str,
    pipelines_dir: Path,
    framework_yaml: Path | None,
    sync: bool,
    no_cache: bool,
    all_pipelines: bool,
) -> None:
    """Compile and submit a pipeline to Vertex AI Pipelines."""
    from gcp_ml_framework.pipeline.compiler import PipelineCompiler
    from gcp_ml_framework.pipeline.runner import VertexRunner

    ctx = load_context(framework_yaml=framework_yaml)

    targets = (
        [p.name for p in pipelines_dir.iterdir() if p.is_dir() and (p / "pipeline.py").exists()]
        if all_pipelines
        else [pipeline_name]
    )

    import datetime

    run_date = datetime.date.today().isoformat()

    for name in targets:
        pipeline_dir = pipelines_dir / name
        pipeline_def = _load_pipeline(pipeline_dir)
        compiler = PipelineCompiler()
        compiled_path = compiler.compile(pipeline_def, ctx)
        runner = VertexRunner(ctx)
        job = runner.submit(
            compiled_path=compiled_path,
            pipeline_name=name,
            parameter_values={"run_date": run_date},
            enable_caching=not no_cache,
            sync=sync,
        )
        console.print(f"[green]Submitted:[/green] {job.resource_name}")


def _run_compile(
    pipeline_name: str,
    pipelines_dir: Path,
    framework_yaml: Path | None,
    output_dir: Path,
    all_pipelines: bool,
) -> None:
    """Compile pipeline(s) to KFP YAML without submitting."""
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
