"""Shared helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from gcp_ml_framework.config import load_config
from gcp_ml_framework.context import MLContext

console = Console()
err_console = Console(stderr=True)


def load_context(
    pipeline_yaml: Path | None = None,
    branch: str | None = None,
) -> MLContext:
    """Load config and build MLContext. Prints a friendly error on failure."""
    try:
        kwargs = {}
        if branch:
            kwargs["branch"] = branch
        cfg = load_config(
            pipeline_yaml=pipeline_yaml,
            **kwargs,
        )
        return MLContext.from_config(cfg)
    except (ImportError, AttributeError, FileNotFoundError) as exc:
        err_console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(1) from exc


def load_pipeline(pipeline_dir: Path):
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


def print_kv_table(title: str, data: dict[str, str]) -> None:
    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")
    for k, v in data.items():
        table.add_row(k, v)
    console.print(table)
