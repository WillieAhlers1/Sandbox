"""
Auto-generated Airflow DAG: training_pipeline
Namespace: mlplatform-second-run-test
GCP project: YOUR_PROJECT_ID

DO NOT EDIT MANUALLY.
Regenerate with: gml compile
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.providers.google.cloud.operators.vertex_ai.pipeline_job import RunPipelineJobOperator

# Ensure Jinja macros in display_name/parameter_values are rendered
RunPipelineJobOperator.template_fields = tuple(
    dict.fromkeys((*RunPipelineJobOperator.template_fields, "display_name", "parameter_values"))
)

_default_args = {
    "owner": "gcp-mlf",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
}

with DAG(
    dag_id="mlplatform_second_run_test__training_pipeline",
    description="GML DAG: training_pipeline",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['mlplatform', 'second-run', 'test'],
    default_args=_default_args,
) as dag:

    run_vertex_pipeline = RunPipelineJobOperator(
        task_id="run_vertex_pipeline",
        project_id="YOUR_PROJECT_ID",
        region="us-east4",
        display_name="training_pipeline_{{ ds_nodash }}",
        template_path="gs://YOUR_PROJECT_ID-mlplatform-second-run/test/pipelines/training_pipeline/pipeline.yaml",
        pipeline_root="gs://YOUR_PROJECT_ID-mlplatform-second-run/test/pipeline_runs/training_pipeline/",
        enable_caching=False,
        deferrable=True,
        service_account="YOUR_SERVICE_ACCOUNT_EMAIL",
        parameter_values={"run_date": "{{ ds }}"},
    )

    # --- Dependencies ---

