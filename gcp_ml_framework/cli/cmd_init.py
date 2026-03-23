"""gml init — scaffold a new project or pipeline."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

init_app = typer.Typer(help="Initialise a new project or pipeline.")
console = Console()

# ── Templates ──────────────────────────────────────────────────────────────────

_DOT_ENV = """\
# GCP ML Framework — project config
# This file is gitignored — never commit real values.

# --- Identity (required) ---
TEAM={team}
PROJECT={project}

# --- Environment ---
ENVIRONMENT=dev

# --- GCP ---
GCP_PROJECT_ID={gcp_project}
GCP_REGION=us-central1

# --- Cloud Composer (fill after provisioning) ---
# GCP_COMPOSER_DAGS_PATH=gs://composer-bucket/dags
# GCP_PIPELINE_SERVICE_ACCOUNT_EMAIL=sa@project.iam.gserviceaccount.com
"""

_PIPELINE_PY = """\
from gcp_ml_framework import Pipeline
from gcp_ml_framework.components.operators.bq_query import BQQuery
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    Pipeline(name="{name}", schedule="@daily")
    .add(BQQuery(
        sql_file="sql/{name}_features.sql",
        destination_table="{name}_features",
    ))
    .add(TrainModel(machine_type="n2-standard-4"))
    .add(EvaluateModel(
        metrics=["auc", "f1"],
        gate={{"auc": 0.75}},
    ))
    .add(DeployModel(model_name="{name}"))
    .build()
)
"""

_PIPELINE_CONFIG_YAML = """\
# Pipeline-level config overrides.
# These are merged on top of .env defaults.
# Only set values that differ from the framework defaults.

# feature_store:
#   sync_schedule: "0 */3 * * *"
"""

_FEATURE_SCHEMA_YAML = """\
entity: user
id_column: user_id
id_type: STRING
feature_groups:
  behavioral:
    description: "Behavioural engagement features"
    features:
      - name: session_count_7d
        type: INT64
      - name: total_purchases_30d
        type: FLOAT64
      - name: days_since_last_login
        type: INT64
  demographic:
    description: "User demographic features"
    features:
      - name: country
        type: STRING
      - name: account_age_days
        type: INT64
"""

_CI_DEV_YAML = """\
name: CI — DEV
on:
  push:
    branches: ["feature/**", "hotfix/**", "fix/**"]

permissions:
  contents: read
  id-token: write

env:
  GCP_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID }}}}
  TEAM: ${{{{ vars.TEAM }}}}
  PROJECT: ${{{{ vars.PROJECT }}}}
  ENVIRONMENT: dev

jobs:
  ci-dev:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_DEV }}}}
          service_account: ${{{{ secrets.SA_EMAIL_DEV }}}}
      - run: uv sync
      - run: uv run ruff check gcp_ml_framework tests
      - run: uv run mypy gcp_ml_framework
      - run: uv run pytest tests/unit/ -v
      - run: gml compile --all
      - run: gml deploy --all
"""

_CI_STAGE_YAML = """\
name: CI — STAGE
on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write

env:
  GCP_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID }}}}
  TEAM: ${{{{ vars.TEAM }}}}
  PROJECT: ${{{{ vars.PROJECT }}}}
  ENVIRONMENT: staging

jobs:
  ci-stage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_STAGING }}}}
          service_account: ${{{{ secrets.SA_EMAIL_STAGING }}}}
      - run: uv sync
      - run: uv run pytest tests/unit/ tests/integration/ -v
      - run: gml deploy --all
      - run: gml run --all
"""

_PROMOTE_YAML = """\
name: Promote — STAGE to PROD
on:
  push:
    tags: ["v[0-9]+.[0-9]+.[0-9]+"]

permissions:
  contents: read
  id-token: write

jobs:
  promote:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_PROD }}}}
          service_account: ${{{{ secrets.SA_EMAIL_PROD }}}}
        env:
          GCP_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID }}}}
          ENVIRONMENT: prod
      - run: uv sync
      # TODO: gml promote is not yet implemented
      # - run: gml promote --from main --to prod --tag ${{{{ github.ref_name }}}}
      - run: gml deploy --all
"""

_TEARDOWN_YAML = """\
name: Teardown — DEV ephemeral resources
on:
  pull_request:
    types: [closed]
  schedule:
    - cron: "0 3 * * *"   # daily sweep for inactive branches

permissions:
  contents: read
  id-token: write

jobs:
  teardown:
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule' || github.event.pull_request.merged == true
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{{{ secrets.WIF_PROVIDER_DEV }}}}
          service_account: ${{{{ secrets.SA_EMAIL_DEV }}}}
        env:
          GCP_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID }}}}
          ENVIRONMENT: dev
      - run: uv sync
      - run: gml teardown --branch ${{{{ github.head_ref }}}} --confirm
"""

_GITIGNORE = """\
.env
__pycache__/
*.py[cod]
.mypy_cache/
.ruff_cache/
.pytest_cache/
dist/
*.egg-info/
compiled_pipelines/
.uv/
"""


# ── Commands ───────────────────────────────────────────────────────────────────


@init_app.command("project")
def init_project(
    team: str = typer.Argument(..., help="Team slug (e.g. 'dsci')"),
    project: str = typer.Argument(..., help="Project name (e.g. 'churn-pred')"),
    gcp_project: str = typer.Option(
        ...,
        "--dev-project",
        "--gcp-project",
        help="GCP project ID",
    ),
    output_dir: Path = typer.Option(Path("."), "--out", "-o", help="Output directory"),
) -> None:
    """
    Scaffold a new gcp-ml-framework project.

    Creates .env, feature_schemas/, CI/CD workflows, and an example pipeline.

    Example:
        gml init project dsci churn-pred --gcp-project my-gcp-dev
    """
    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    _write(
        root / ".env",
        _DOT_ENV.format(
            team=team,
            project=project,
            gcp_project=gcp_project,
        ),
    )
    _write(root / ".python-version", "3.12\n")
    _write(root / ".gitignore", _GITIGNORE)
    _write(root / ".env.example", Path(__file__).parent.parent.parent / ".env.example")
    _write(root / "feature_schemas" / "user.yaml", _FEATURE_SCHEMA_YAML)

    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    _write(wf / "ci-dev.yaml", _CI_DEV_YAML)
    _write(wf / "ci-stage.yaml", _CI_STAGE_YAML)
    _write(wf / "promote.yaml", _PROMOTE_YAML)
    _write(wf / "teardown.yaml", _TEARDOWN_YAML)

    (root / "pipelines").mkdir(exist_ok=True)
    (root / "dags").mkdir(exist_ok=True)
    (root / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    _write(root / "tests" / "conftest.py", "# Add shared pytest fixtures here.\n")

    console.print(f"\n[bold green]Project scaffolded at {root}[/bold green]\n")
    console.print("Next steps:")
    console.print("  1. Edit [cyan].env[/cyan] — add your Composer env name")
    console.print(f"  2. Run [cyan]gml init pipeline {project}[/cyan] to add a pipeline")
    console.print("  3. Run [cyan]gml context show[/cyan] to verify your setup\n")


@init_app.command("pipeline")
def init_pipeline(
    name: str = typer.Argument(..., help="Pipeline name (snake_case, e.g. 'churn_prediction')"),
    output_dir: Path = typer.Option(Path("pipelines"), "--out", "-o"),
) -> None:
    """
    Scaffold a new pipeline inside an existing project.

    Creates pipeline.py, config.yaml, and SQL templates.

    Examples:
        gml init pipeline churn_prediction
    """
    pipeline_dir = output_dir / name
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    _write(pipeline_dir / "pipeline.py", _PIPELINE_PY.format(name=name))
    _write(pipeline_dir / "config.yaml", _PIPELINE_CONFIG_YAML)
    sql_dir = pipeline_dir / "sql"
    sql_dir.mkdir(exist_ok=True)
    _write(
        sql_dir / f"{name}_features.sql",
        f"-- Feature SQL for {name}\nSELECT\n  entity_id,\n"
        "  -- add features here\n"
        "FROM `{{bq_dataset}}.raw_events`\n",
    )
    console.print(f"\n[bold green]Pipeline '{name}' scaffolded at {pipeline_dir}[/bold green]\n")
    console.print(f"  Edit [cyan]pipelines/{name}/pipeline.py[/cyan] to define your steps.\n")


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, Path):
        if content.exists():
            path.write_text(content.read_text())
    else:
        path.write_text(content)
