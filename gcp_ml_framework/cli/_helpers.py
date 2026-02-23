"""Shared helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from gcp_ml_framework.config import FrameworkConfig, load_config
from gcp_ml_framework.context import MLContext

console = Console()
err_console = Console(stderr=True)


def load_context(
    framework_yaml: Optional[Path] = None,
    pipeline_yaml: Optional[Path] = None,
    branch: Optional[str] = None,
) -> MLContext:
    """Load config and build MLContext. Prints a friendly error on failure."""
    try:
        kwargs = {}
        if branch:
            kwargs["branch"] = branch
        cfg = load_config(
            framework_yaml=framework_yaml,
            pipeline_yaml=pipeline_yaml,
            **kwargs,
        )
        return MLContext.from_config(cfg)
    except Exception as exc:
        err_console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(1) from exc


def print_kv_table(title: str, data: dict[str, str]) -> None:
    table = Table(title=title, show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim")
    table.add_column("Value", style="bold")
    for k, v in data.items():
        table.add_row(k, v)
    console.print(table)
