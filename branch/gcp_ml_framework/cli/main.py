"""
gml — GCP ML Framework CLI entrypoint.

All sub-commands are registered here. Each sub-app lives in its own module.
"""

import typer

from gcp_ml_framework.cli.cmd_context import context_app
from gcp_ml_framework.cli.cmd_deploy import deploy_app
from gcp_ml_framework.cli.cmd_init import init_app
from gcp_ml_framework.cli.cmd_promote import promote_app
from gcp_ml_framework.cli.cmd_run import run
from gcp_ml_framework.cli.cmd_teardown import teardown_app

app = typer.Typer(
    name="gml",
    help="GCP ML Framework — branch-isolated ML pipelines on GCP.",
    add_completion=True,
    no_args_is_help=True,
)

app.add_typer(init_app, name="init")
app.add_typer(context_app, name="context")
app.command("run")(run)
app.add_typer(deploy_app, name="deploy")
app.add_typer(promote_app, name="promote")
app.add_typer(teardown_app, name="teardown")

if __name__ == "__main__":
    app()
