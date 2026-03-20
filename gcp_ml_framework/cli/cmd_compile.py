"""gml compile — compile pipelines/DAGs to deployable artifacts."""

from __future__ import annotations

from pathlib import Path

import typer

from gcp_ml_framework.cli._helpers import console, err_console, load_context


def compile_cmd(
    name: str = typer.Argument(
        "", help="Pipeline/DAG name to compile (directory name under pipelines/)"
    ),
    all_pipelines: bool = typer.Option(False, "--all", help="Compile all pipelines"),
    pipelines_dir: Path = typer.Option(Path("pipelines"), "--pipelines-dir"),
    output_dir: Path = typer.Option(
        Path("compiled_pipelines"), "--out", help="Output dir for compiled YAML"
    ),
    dags_dir: Path = typer.Option(
        Path("dags"), "--dags-dir", help="Output dir for generated DAG files"
    ),
    framework_yaml: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """
    Compile pipeline(s) to KFP YAML and/or Airflow DAG files.

    - pipeline.py → KFP YAML + auto-wrapped DAG file
    - dag.py → DAG file + KFP YAML for any embedded VertexPipelineTasks

    Examples:\n
        gml compile churn_prediction\n
        gml compile --all\n
    """
    if not name and not all_pipelines:
        err_console.print("[red]Error:[/red] Provide a pipeline name or use --all.")
        raise typer.Exit(1)

    ctx = load_context(framework_yaml=framework_yaml)

    targets = _discover_targets(pipelines_dir, name, all_pipelines)
    if not targets:
        err_console.print("[yellow]No pipelines found.[/yellow]")
        raise typer.Exit(1)

    for pipeline_name in targets:
        pipeline_dir = pipelines_dir / pipeline_name
        has_pipeline_py = (pipeline_dir / "pipeline.py").exists()
        has_dag_py = (pipeline_dir / "dag.py").exists()

        if has_pipeline_py and has_dag_py:
            err_console.print(
                f"[red]Error:[/red] {pipeline_name}/ has both pipeline.py and dag.py. Use only one."
            )
            raise typer.Exit(1)

        if not has_pipeline_py and not has_dag_py:
            err_console.print(
                f"[red]Error:[/red] {pipeline_name}/ has neither pipeline.py nor dag.py."
            )
            raise typer.Exit(1)

        if has_pipeline_py:
            _compile_pipeline(pipeline_name, pipeline_dir, ctx, output_dir, dags_dir)
        else:
            _compile_dag(pipeline_name, pipeline_dir, ctx, output_dir, dags_dir)


def _discover_targets(pipelines_dir: Path, name: str, all_pipelines: bool) -> list[str]:
    """Return list of pipeline directory names to compile."""
    if all_pipelines:
        return [
            p.name
            for p in pipelines_dir.iterdir()
            if p.is_dir() and ((p / "pipeline.py").exists() or (p / "dag.py").exists())
        ]
    return [name]


def _compile_pipeline(
    pipeline_name: str, pipeline_dir: Path, ctx, output_dir: Path, dags_dir: Path
) -> None:
    """Compile a pipeline.py → KFP YAML + auto-wrapped DAG file."""
    from gcp_ml_framework.pipeline.compiler import PipelineCompiler

    pipeline_def = _load_pipeline(pipeline_dir)
    compiler = PipelineCompiler(output_dir=output_dir)
    yaml_path = compiler.compile(pipeline_def, ctx, pipeline_dir=pipeline_dir)
    console.print(f"[green]Compiled KFP YAML:[/green] {yaml_path}")

    # Auto-wrap in a DAG file
    from gcp_ml_framework.dag.factory import auto_wrap_pipeline_dag

    dag_path = auto_wrap_pipeline_dag(pipeline_def, ctx, dags_dir)
    console.print(f"[green]Generated DAG:[/green] {dag_path}")


def _compile_dag(
    pipeline_name: str, pipeline_dir: Path, ctx, output_dir: Path, dags_dir: Path
) -> None:
    """Compile a dag.py → DAG file + KFP YAML for embedded VertexPipelineTasks."""
    from gcp_ml_framework.dag.factory import discover_and_render

    dag_filename, dag_content = discover_and_render(pipeline_dir, ctx)
    dags_dir.mkdir(parents=True, exist_ok=True)
    dag_path = dags_dir / dag_filename
    dag_path.write_text(dag_content)
    console.print(f"[green]Generated DAG:[/green] {dag_path}")

    # Compile any embedded VertexPipelineTasks to KFP YAML
    _compile_embedded_vertex_pipelines(pipeline_dir, ctx, output_dir)


def _compile_embedded_vertex_pipelines(pipeline_dir: Path, ctx, output_dir: Path) -> None:
    """If a DAG has VertexPipelineTasks, compile their pipelines to YAML."""
    dag_def = _load_dag(pipeline_dir)
    from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

    for dag_task in dag_def.tasks:
        if isinstance(dag_task.task, VertexPipelineTask) and dag_task.task.pipeline_name:
            # Inline pipeline object takes priority over disk discovery
            if dag_task.task.pipeline is not None:
                from gcp_ml_framework.pipeline.compiler import PipelineCompiler

                compiler = PipelineCompiler(output_dir=output_dir)
                # Use the parent pipeline_dir (where trainer/ lives)
                yaml_path = compiler.compile(dag_task.task.pipeline, ctx, pipeline_dir=pipeline_dir)
                console.print(f"[green]Compiled embedded pipeline:[/green] {yaml_path}")
            else:
                vp_name = dag_task.task.pipeline_name
                vp_dir = pipeline_dir.parent / vp_name
                if (vp_dir / "pipeline.py").exists():
                    from gcp_ml_framework.pipeline.compiler import PipelineCompiler

                    pipeline_def = _load_pipeline(vp_dir)
                    compiler = PipelineCompiler(output_dir=output_dir)
                    yaml_path = compiler.compile(pipeline_def, ctx, pipeline_dir=vp_dir)
                    console.print(f"[green]Compiled embedded pipeline:[/green] {yaml_path}")


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
