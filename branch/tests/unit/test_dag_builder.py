"""Unit tests for dag/builder.py — DAGBuilder DSL."""

import pytest

from gcp_ml_framework.dag.builder import DAGBuilder, DAGDefinition
from gcp_ml_framework.dag.tasks.bq_query import BQQueryTask
from gcp_ml_framework.dag.tasks.email import EmailTask

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def simple_dag() -> DAGDefinition:
    return (
        DAGBuilder(name="test-dag", schedule="@daily")
        .task(BQQueryTask(sql="SELECT 1"), name="step_1")
        .task(BQQueryTask(sql="SELECT 2"), name="step_2")
        .build()
    )


@pytest.fixture
def etl_dag() -> DAGDefinition:
    return (
        DAGBuilder(
            name="daily-etl",
            schedule="30 7 * * *",
            description="Daily ETL",
            tags=["etl", "sales"],
        )
        .task(BQQueryTask(sql="SELECT 1", destination_table="raw"), name="extract")
        .task(BQQueryTask(sql="SELECT 2", destination_table="summary"), name="transform")
        .task(
            EmailTask(to=["a@b.com"], subject="done", body="ETL complete"),
            name="notify",
        )
        .build()
    )


# ── DAGBuilder tests ─────────────────────────────────────────────────────────


class TestDAGBuilder:
    def test_returns_dag_definition(self, simple_dag):
        assert isinstance(simple_dag, DAGDefinition)

    def test_name_preserved(self, simple_dag):
        assert simple_dag.name == "test-dag"

    def test_schedule_preserved(self, simple_dag):
        assert simple_dag.schedule == "@daily"

    def test_description_preserved(self, etl_dag):
        assert etl_dag.description == "Daily ETL"

    def test_tags_preserved(self, etl_dag):
        assert etl_dag.tags == ["etl", "sales"]

    def test_task_count(self, simple_dag):
        assert len(simple_dag.tasks) == 2

    def test_etl_task_count(self, etl_dag):
        assert len(etl_dag.tasks) == 3

    def test_task_names(self, etl_dag):
        assert etl_dag.task_names == ["extract", "transform", "notify"]

    def test_schedule_none(self):
        dag = (
            DAGBuilder(name="manual", schedule=None)
            .task(BQQueryTask(sql="SELECT 1"), name="t")
            .build()
        )
        assert dag.schedule is None


class TestDAGBuilderSequentialDefault:
    """When depends_on is not specified, tasks depend on the previous task."""

    def test_first_task_has_no_deps(self, simple_dag):
        assert simple_dag.tasks[0].depends_on == []

    def test_second_task_depends_on_first(self, simple_dag):
        assert simple_dag.tasks[1].depends_on == ["step_1"]

    def test_third_task_depends_on_second(self, etl_dag):
        assert etl_dag.tasks[2].depends_on == ["transform"]


class TestDAGBuilderExplicitDependencies:
    def test_explicit_depends_on_string(self):
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a")
            .task(BQQueryTask(sql="SELECT 2"), name="b")
            .task(BQQueryTask(sql="SELECT 3"), name="c", depends_on="a")
            .build()
        )
        assert dag.tasks[2].depends_on == ["a"]

    def test_explicit_depends_on_list(self):
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3"), name="c", depends_on=["a", "b"])
            .build()
        )
        assert dag.tasks[2].depends_on == ["a", "b"]

    def test_depends_on_empty_list_makes_root(self):
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a")
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .build()
        )
        # Both are roots
        assert dag.tasks[0].depends_on == []
        assert dag.tasks[1].depends_on == []

    def test_parallel_then_fan_in(self):
        """Three parallel roots → one join task."""
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3"), name="c", depends_on=[])
            .task(BQQueryTask(sql="SELECT 4"), name="join", depends_on=["a", "b", "c"])
            .build()
        )
        assert dag.tasks[3].depends_on == ["a", "b", "c"]


class TestDAGBuilderValidation:
    def test_empty_dag_raises(self):
        with pytest.raises(ValueError, match="no tasks"):
            DAGBuilder(name="empty").build()

    def test_duplicate_name_raises(self):
        with pytest.raises(ValueError, match="Duplicate"):
            (
                DAGBuilder(name="d")
                .task(BQQueryTask(sql="SELECT 1"), name="same")
                .task(BQQueryTask(sql="SELECT 2"), name="same")
                .build()
            )

    def test_unknown_depends_on_raises(self):
        with pytest.raises(ValueError, match="Unknown"):
            (
                DAGBuilder(name="d")
                .task(BQQueryTask(sql="SELECT 1"), name="a")
                .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on="nonexistent")
                .build()
            )

    def test_cycle_raises(self):
        """A task cannot depend on itself."""
        with pytest.raises(ValueError, match="Unknown"):
            (
                DAGBuilder(name="d")
                .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on="a")
                .build()
            )


class TestDAGDefinition:
    def test_root_tasks(self):
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3"), name="c", depends_on=["a", "b"])
            .build()
        )
        roots = dag.root_tasks
        root_names = [t.name for t in roots]
        assert root_names == ["a", "b"]

    def test_topological_order(self, etl_dag):
        ordered = etl_dag.topological_order()
        names = [t.name for t in ordered]
        assert names.index("extract") < names.index("transform")
        assert names.index("transform") < names.index("notify")

    def test_topological_order_parallel(self):
        dag = (
            DAGBuilder(name="d", schedule="@daily")
            .task(BQQueryTask(sql="SELECT 1"), name="a", depends_on=[])
            .task(BQQueryTask(sql="SELECT 2"), name="b", depends_on=[])
            .task(BQQueryTask(sql="SELECT 3"), name="join", depends_on=["a", "b"])
            .build()
        )
        ordered = dag.topological_order()
        names = [t.name for t in ordered]
        # Both a and b must come before join
        assert names.index("a") < names.index("join")
        assert names.index("b") < names.index("join")
