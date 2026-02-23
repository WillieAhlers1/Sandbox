"""gml init — scaffold a new project or pipeline."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

init_app = typer.Typer(help="Initialise a new project or pipeline.")
console = Console()

# ── Templates ──────────────────────────────────────────────────────────────────

_FRAMEWORK_YAML = """\
team: {team}
project: {project}
gcp:
  dev_project_id: {dev_project}
  staging_project_id: {staging_project}
  prod_project_id: {prod_project}
  region: us-central1
  composer_env:              # fill in your Composer env name
  artifact_registry_host: us-central1-docker.pkg.dev

secrets:
  secret_prefix:             # defaults to namespace token; override only if needed
"""

_PIPELINE_PY = """\
from gcp_ml_framework.pipeline.builder import PipelineBuilder
from gcp_ml_framework.components.ingestion.bigquery_extract import BigQueryExtract
from gcp_ml_framework.components.transformation.bq_transform import BQTransform
from gcp_ml_framework.components.feature_store.write_features import WriteFeatures
from gcp_ml_framework.components.ml.train import TrainModel
from gcp_ml_framework.components.ml.evaluate import EvaluateModel
from gcp_ml_framework.components.ml.deploy import DeployModel

pipeline = (
    PipelineBuilder(name="{name}", schedule="@daily")
    .ingest(
        BigQueryExtract(
            query="SELECT * FROM `{{bq_dataset}}.raw_events` WHERE dt = '{{run_date}}'",
            output_table="raw_events_extract",
        )
    )
    .transform(
        BQTransform(
            sql_file="sql/{name}_features.sql",
            output_table="{name}_features",
        )
    )
    .write_features(
        WriteFeatures(
            entity="user",
            feature_group="{name}_signals",
            entity_id_column="user_id",
        )
    )
    .train(
        TrainModel(
            trainer_image="{{artifact_registry}}/{name}-trainer:latest",
            machine_type="n1-standard-4",
        )
    )
    .evaluate(
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={{"auc": 0.75}},
        )
    )
    .deploy(
        DeployModel(
            endpoint_name="{name}-endpoint",
        )
    )
    .build()
)
"""

_PIPELINE_CONFIG_YAML = """\
# Pipeline-level config overrides.
# These are merged on top of framework.yaml.
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
  GML_GCP__DEV_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_DEV }}}}
  GML_TEAM: ${{{{ vars.GML_TEAM }}}}
  GML_PROJECT: ${{{{ vars.GML_PROJECT }}}}

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
      - run: gml run --compile-only --all
      - run: gml deploy dags
      - run: gml deploy features
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
  GML_GCP__STAGING_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_STAGING }}}}
  GML_TEAM: ${{{{ vars.GML_TEAM }}}}
  GML_PROJECT: ${{{{ vars.GML_PROJECT }}}}

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
      - run: gml deploy dags
      - run: gml deploy features
      - run: gml run --vertex --all --sync
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
          GML_GCP__STAGING_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_STAGING }}}}
          GML_GCP__PROD_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_PROD }}}}
      - run: uv sync
      - run: gml promote --from main --to prod --tag ${{{{ github.ref_name }}}}
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
          GML_GCP__DEV_PROJECT_ID: ${{{{ vars.GCP_PROJECT_ID_DEV }}}}
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
    dev_project: str = typer.Option(..., "--dev-project", help="DEV GCP project ID"),
    staging_project: str = typer.Option("", "--staging-project", help="STAGING GCP project ID"),
    prod_project: str = typer.Option("", "--prod-project", help="PROD GCP project ID"),
    output_dir: Path = typer.Option(Path("."), "--out", "-o", help="Output directory"),
) -> None:
    """
    Scaffold a new gcp-ml-framework project.

    Creates framework.yaml, feature_schemas/, CI/CD workflows, and an example pipeline.

    Example:
        gml init project dsci churn-pred --dev-project my-gcp-dev
    """
    staging_project = staging_project or f"{dev_project}-staging"
    prod_project = prod_project or f"{dev_project}-prod"

    root = output_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)

    _write(root / "framework.yaml", _FRAMEWORK_YAML.format(
        team=team, project=project,
        dev_project=dev_project,
        staging_project=staging_project,
        prod_project=prod_project,
    ))
    _write(root / ".python-version", "3.11\n")
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
    console.print(f"  1. Edit [cyan]framework.yaml[/cyan] — add your Composer env name")
    console.print(f"  2. Run [cyan]gml init pipeline {project}[/cyan] to add a pipeline")
    console.print(f"  3. Run [cyan]gml context show[/cyan] to verify your setup\n")


@init_app.command("pipeline")
def init_pipeline(
    name: str = typer.Argument(..., help="Pipeline name (snake_case, e.g. 'churn_prediction')"),
    output_dir: Path = typer.Option(Path("pipelines"), "--out", "-o"),
) -> None:
    """
    Scaffold a new pipeline inside an existing project.

    Creates pipeline.py, config.yaml, and a placeholder SQL file.

    Example:
        gml init pipeline churn_prediction
    """
    pipeline_dir = output_dir / name
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    _write(pipeline_dir / "pipeline.py", _PIPELINE_PY.format(name=name))
    _write(pipeline_dir / "config.yaml", _PIPELINE_CONFIG_YAML)

    sql_dir = pipeline_dir / "sql"
    sql_dir.mkdir(exist_ok=True)
    _write(sql_dir / f"{name}_features.sql", f"-- Feature SQL for {name}\nSELECT\n  entity_id,\n  -- add features here\nFROM `{{{{bq_dataset}}}}.raw_events`\n")

    console.print(f"\n[bold green]Pipeline '{name}' scaffolded at {pipeline_dir}[/bold green]\n")
    console.print(f"  Edit [cyan]pipelines/{name}/pipeline.py[/cyan] to define your steps.\n")


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, Path):
        if content.exists():
            path.write_text(content.read_text())
    else:
        path.write_text(content)
