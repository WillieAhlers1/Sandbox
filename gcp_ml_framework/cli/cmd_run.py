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
    local: bool = typer.Option(False, "--local", help="Run locally using DuckDB/pandas stubs"),
    vertex: bool = typer.Option(
        False, "--vertex", help="Compile and submit to Vertex AI Pipelines"
    ),
    composer: bool = typer.Option(
        False, "--composer", help="Trigger an already-deployed DAG on Composer"
    ),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print execution plan without running"),
    sync: bool = typer.Option(
        False, "--sync", help="Block until the Vertex pipeline run completes"
    ),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable KFP step caching"),
    all_pipelines: bool = typer.Option(False, "--all", help="Run all pipelines in pipelines/"),
    run_date: str = typer.Option(
        "",
        "--run-date",
        help="Override run_date (default: today). Seed data requires specific dates "
        "for correct results — e.g. 2024-01-01 for churn_prediction, 2026-03-01 for sales_analytics.",
    ),
) -> None:
    """
    Run a pipeline locally, on Vertex AI, or trigger on Composer.

    Defaults to --local if no mode flag is given.

    Examples:\n
        gml run example_churn --local\n
        gml run example_churn --local --dry-run\n
        gml run example_churn --vertex --sync\n
        gml run sales_analytics --composer --run-date 2026-03-01\n
        gml run --vertex --all\n
    """
    # Validate mutually exclusive flags
    mode_count = sum([local, vertex, composer])
    if mode_count > 1:
        err_console.print(
            "[red]Error:[/red] --local, --vertex, and --composer are mutually exclusive."
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
        _run_local(pipeline_name, pipelines_dir, framework_yaml, dry_run, run_date)
    elif vertex:
        _run_vertex(
            pipeline_name, pipelines_dir, framework_yaml, sync, no_cache, all_pipelines, run_date
        )
    elif composer:
        _run_composer(pipeline_name, framework_yaml, run_date)


def _load_dag(pipeline_dir: Path):
    """Import a dag.py and return its DAGDefinition."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("_dag", pipeline_dir / "dag.py")
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"No dag.py found in {pipeline_dir}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_dag"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    if not hasattr(mod, "dag"):
        raise AttributeError(f"{pipeline_dir}/dag.py must define a `dag` variable")
    return mod.dag


def _run_local(
    pipeline_name: str,
    pipelines_dir: Path,
    framework_yaml: Path | None,
    dry_run: bool,
    run_date: str = "",
) -> None:
    """Run a pipeline locally using DuckDB/pandas stubs."""
    pipeline_dir = pipelines_dir / pipeline_name
    ctx = load_context(
        framework_yaml=framework_yaml,
        pipeline_yaml=pipeline_dir / "config.yaml"
        if (pipeline_dir / "config.yaml").exists()
        else None,
    )

    seeds_dir = pipeline_dir / "seeds"

    if (pipeline_dir / "dag.py").exists():
        # Use DAG local runner
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        dag_def = _load_dag(pipeline_dir)
        runner = DAGLocalRunner(
            ctx,
            seeds_dir=seeds_dir if seeds_dir.exists() else None,
            pipeline_dir=pipeline_dir,
        )
        if dry_run:
            for task in dag_def.topological_order():
                console.print(f"[dim][dry-run][/dim] {task.name} ({task.task.task_type})")
        else:
            console.print(f"[cyan]Running {pipeline_name!r} DAG locally...[/cyan]")
            runner.run(dag_def, run_date=run_date)
            console.print("[green]Done.[/green]")
    elif (pipeline_dir / "pipeline.py").exists():
        # Use pipeline local runner (existing)
        from gcp_ml_framework.pipeline.runner import LocalRunner

        pipeline_def = _load_pipeline(pipeline_dir)
        runner = LocalRunner(ctx, seeds_dir=seeds_dir if seeds_dir.exists() else None)
        if dry_run:
            runner.print_plan(pipeline_def)
        else:
            console.print(f"[cyan]Running {pipeline_name!r} locally...[/cyan]")
            runner.run(pipeline_def, run_date=run_date)
            console.print("[green]Done.[/green]")
    else:
        err_console.print(f"[red]Error:[/red] {pipeline_name}/ has neither pipeline.py nor dag.py.")
        raise typer.Exit(1)


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
