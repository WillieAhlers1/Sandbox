"""Unit tests for dag/tasks/ — BQQueryTask, EmailTask, VertexPipelineTask."""

from gcp_ml_framework.dag.tasks.base import BaseTask, TaskConfig
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask
from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

# ── BQQueryTask ───────────────────────────────────────────────────────────────


class TestBQQueryTask:
    def test_is_base_task(self):
        t = BQQueryTask(sql="SELECT 1")
        assert isinstance(t, BaseTask)

    def test_task_type(self):
        t = BQQueryTask(sql="SELECT 1")
        assert t.task_type == "bq_query"

    def test_sql_stored(self):
        t = BQQueryTask(sql="SELECT * FROM orders")
        assert t.sql == "SELECT * FROM orders"

    def test_destination_table_stored(self):
        t = BQQueryTask(sql="SELECT 1", destination_table="output")
        assert t.destination_table == "output"

    def test_destination_table_default_none(self):
        t = BQQueryTask(sql="SELECT 1")
        assert t.destination_table is None

    def test_write_disposition_default(self):
        t = BQQueryTask(sql="SELECT 1")
        assert t.write_disposition == "WRITE_TRUNCATE"

    def test_validate_empty_sql(self, test_context):
        t = BQQueryTask(sql="")
        errors = t.validate(test_context)
        assert any("sql" in e.lower() for e in errors)

    def test_validate_good_sql(self, test_context):
        t = BQQueryTask(sql="SELECT 1")
        errors = t.validate(test_context)
        assert errors == []

    def test_resolve_templates(self, test_context):
        t = BQQueryTask(
            sql="SELECT * FROM `{bq_dataset}.orders` WHERE dt = '{run_date}'",
            destination_table="staged",
        )
        resolved = t.resolve_sql(test_context)
        assert test_context.bq_dataset in resolved
        # {run_date} is converted to Airflow macro
        assert "{{ ds }}" in resolved
        assert "{run_date}" not in resolved

    def test_resolve_destination_table(self, test_context):
        t = BQQueryTask(sql="SELECT 1", destination_table="my_table")
        fq = t.resolve_destination(test_context)
        assert fq["datasetId"] == test_context.bq_dataset
        assert fq["tableId"] == "my_table"
        assert fq["projectId"] == test_context.gcp_project

    def test_resolve_destination_none(self, test_context):
        t = BQQueryTask(sql="SELECT 1")
        assert t.resolve_destination(test_context) is None

    def test_default_config(self):
        t = BQQueryTask(sql="SELECT 1")
        assert t.config.retries == 1
        assert t.config.retry_delay_minutes == 5


# ── EmailTask ─────────────────────────────────────────────────────────────────


class TestEmailTask:
    def test_is_base_task(self):
        t = EmailTask(to=["a@b.com"], subject="hi", body="hello")
        assert isinstance(t, BaseTask)

    def test_task_type(self):
        t = EmailTask(to=["a@b.com"], subject="hi")
        assert t.task_type == "email"

    def test_fields_stored(self):
        t = EmailTask(to=["a@b.com", "c@d.com"], subject="sub", body="bod")
        assert t.to == ["a@b.com", "c@d.com"]
        assert t.subject == "sub"
        assert t.body == "bod"

    def test_validate_no_recipients(self, test_context):
        t = EmailTask(to=[], subject="hi")
        errors = t.validate(test_context)
        assert any("recipient" in e.lower() for e in errors)

    def test_validate_no_subject(self, test_context):
        t = EmailTask(to=["a@b.com"], subject="")
        errors = t.validate(test_context)
        assert any("subject" in e.lower() for e in errors)

    def test_validate_good(self, test_context):
        t = EmailTask(to=["a@b.com"], subject="hello", body="world")
        errors = t.validate(test_context)
        assert errors == []

    def test_resolve_subject(self, test_context):
        t = EmailTask(
            to=["a@b.com"],
            subject="[{namespace}] ETL done {run_date}",
            body="done",
        )
        resolved = t.resolve_subject(test_context)
        assert test_context.namespace in resolved
        assert "{{ ds }}" in resolved

    def test_resolve_body(self, test_context):
        t = EmailTask(
            to=["a@b.com"],
            subject="hi",
            body="Dataset: {bq_dataset}, Date: {run_date}",
        )
        resolved = t.resolve_body(test_context)
        assert test_context.bq_dataset in resolved
        assert "{{ ds }}" in resolved


# ── VertexPipelineTask ────────────────────────────────────────────────────────


class TestVertexPipelineTask:
    def test_is_base_task(self):
        t = VertexPipelineTask(pipeline_name="churn_prediction")
        assert isinstance(t, BaseTask)

    def test_task_type(self):
        t = VertexPipelineTask(pipeline_name="churn_prediction")
        assert t.task_type == "vertex_pipeline"

    def test_pipeline_name_stored(self):
        t = VertexPipelineTask(pipeline_name="churn_prediction")
        assert t.pipeline_name == "churn_prediction"

    def test_enable_caching_default_false(self):
        t = VertexPipelineTask(pipeline_name="p")
        assert t.enable_caching is False

    def test_sync_default_true(self):
        t = VertexPipelineTask(pipeline_name="p")
        assert t.sync is True

    def test_validate_empty_name(self, test_context):
        t = VertexPipelineTask(pipeline_name="")
        errors = t.validate(test_context)
        assert any("pipeline_name" in e.lower() for e in errors)

    def test_validate_good(self, test_context):
        t = VertexPipelineTask(pipeline_name="churn_prediction")
        errors = t.validate(test_context)
        assert errors == []


# ── TaskConfig ────────────────────────────────────────────────────────────────


class TestTaskConfig:
    def test_defaults(self):
        c = TaskConfig()
        assert c.retries == 1
        assert c.retry_delay_minutes == 5
        assert c.timeout_hours == 1
        assert c.email_on_failure is True

    def test_override(self):
        c = TaskConfig(retries=3, timeout_hours=2)
        assert c.retries == 3
        assert c.timeout_hours == 2
