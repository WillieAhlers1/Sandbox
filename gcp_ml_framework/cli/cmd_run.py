"""gml run — run pipelines locally or on Vertex AI."""

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
    vertex: bool = typer.Option(
        False, "--vertex", help="Compile and submit to Vertex AI Pipelines"
    ),
    composer: bool = typer.Option(
        False, "--composer", help="Trigger an already-deployed DAG on Composer"
    ),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
    sync: bool = typer.Option(
        False, "--sync", help="Block until the Vertex pipeline run completes"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable KFP step caching"),
    all_pipelines: bool = typer.Option(False, "--all", help="Run all pipelines in pipelines/"),
    run_date: str = typer.Option(
        "",
        "--run-date",
        help="Override run_date (default: today).",
    ),
) -> None:
    """
    Run a pipeline on Vertex AI or trigger on Composer.

    Defaults to --vertex if no mode flag is given.

    Examples:\n
        gml run example_churn --vertex --sync\n
        gml run sales_analytics --composer --run-date 2026-03-01\n
        gml run --vertex --all\n
    """
    # Validate mutually exclusive flags
    mode_count = sum([vertex, composer])
    if mode_count > 1:
        err_console.print(
            "[red]Error:[/red] --vertex and --composer are mutually exclusive."
        )
        raise typer.Exit(1)

    # Default to --vertex if no flag given
    if mode_count == 0:
        vertex = True

    # Validate pipeline_name is given unless --all is used
    if not pipeline_name and not all_pipelines:
        err_console.print("[red]Error:[/red] Provide a pipeline name or use --all.")
        raise typer.Exit(1)

    if vertex:
        _run_vertex(
            pipeline_name, pipelines_dir, framework_yaml, sync, no_cache, all_pipelines, run_date
        )
    elif composer:
        _run_composer(pipeline_name, framework_yaml, run_date)


def _run_vertex(
    pipeline_name: str,
    pipelines_dir: Path,
    framework_yaml: Path | None,
    sync: bool,
    no_cache: bool,
    all_pipelines: bool,
    run_date_override: str = "",
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

    run_date = run_date_override or datetime.date.today().isoformat()

    for name in targets:
        pipeline_dir = pipelines_dir / name
        if (pipeline_dir / "dag.py").exists() and not (pipeline_dir / "pipeline.py").exists():
            err_console.print(
                f"[red]Error:[/red] '{name}' is a DAG-based pipeline (dag.py only). "
                f"Use [bold]--composer[/bold] to run on Composer, or [bold]--local[/bold] to run locally."
            )
            raise typer.Exit(1)
        pipeline_def = _load_pipeline(pipeline_dir)
        compiler = PipelineCompiler()
        compiled_path = compiler.compile(pipeline_def, ctx, pipeline_dir=pipeline_dir)
        runner = VertexRunner(ctx)
        job = runner.submit(
            compiled_path=compiled_path,
            pipeline_name=name,
            parameter_values={"run_date": run_date},
            enable_caching=not no_cache,
            sync=sync,
        )
        console.print(f"[green]Submitted:[/green] {job.resource_name}")


def _run_composer(
    pipeline_name: str,
    framework_yaml: Path | None,
    run_date: str,
) -> None:
    """Trigger an already-deployed DAG on Cloud Composer."""
    from gcp_ml_framework.dag.runner import ComposerRunner

    ctx = load_context(framework_yaml=framework_yaml)

    runner = ComposerRunner(ctx)
    dag_id = runner.resolve_dag_id(pipeline_name)

    console.print(f"[cyan]Triggering DAG '{dag_id}' on Composer...[/cyan]")

    # Ensure DAG is unpaused — Composer 3 defaults new DAGs to paused
    runner.unpause_dag(dag_id)

    result = runner.trigger_dag(pipeline_name, run_date=run_date)

    console.print("[green]DAG run triggered.[/green]")
    console.print(f"  DAG run ID: {result.get('dag_run_id', 'unknown')}")
    console.print(f"  State: {result.get('state', 'unknown')}")

    # Print Airflow UI link
    airflow_uri = runner._get_airflow_uri()
    console.print(f"\n[bold]Airflow UI:[/bold] {airflow_uri}/dags/{dag_id}/grid")
