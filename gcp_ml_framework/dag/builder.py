"""
DAGBuilder — fluent DSL for defining Composer DAGs.

A data scientist edits exactly one file (dag.py) to define their orchestration
workflow. No Airflow DAG code, no operator wiring, no imports from airflow.

Usage:
    dag = (
        DAGBuilder(name="daily-etl", schedule="@daily")
        .task(BQQueryTask(sql="SELECT ..."), name="extract")
        .task(BQQueryTask(sql="SELECT ..."), name="transform")
        .task(EmailTask(to=["team@co.com"], subject="done"), name="notify")
        .build()
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gcp_ml_framework.dag.tasks.base import BaseTask


@dataclass
class DAGTask:
    """A single task in the DAG."""

    name: str
    task: BaseTask
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DAGDefinition:
    """
    Immutable result of DAGBuilder.build().

    Passed to:
    - DAGCompiler  (→ Airflow DAG Python file for Composer)
    - LocalDAGRunner (→ DuckDB-based local execution, future)
    """

    name: str
    schedule: str | None
    tasks: list[DAGTask] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def task_names(self) -> list[str]:
        return [t.name for t in self.tasks]

    @property
    def root_tasks(self) -> list[DAGTask]:
        """Tasks with no dependencies (DAG entry points)."""
        return [t for t in self.tasks if not t.depends_on]

    def topological_order(self) -> list[DAGTask]:
        """Return tasks in a valid execution order."""
        by_name = {t.name: t for t in self.tasks}
        visited: set[str] = set()
        result: list[DAGTask] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            for dep in by_name[name].depends_on:
                visit(dep)
            result.append(by_name[name])

        for t in self.tasks:
            visit(t.name)
        return result


class DAGBuilder:
    """
    Fluent builder for Composer DAG definitions.

    Tasks are sequential by default (like PipelineBuilder). Use explicit
    depends_on for parallel branches or fan-in patterns.
    """

    def __init__(
        self,
        name: str,
        schedule: str | None = "@daily",
        description: str = "",
        tags: list[str] | None = None,
    ) -> None:
        self._name = name
        self._schedule = schedule
        self._description = description
        self._tags = tags or []
        self._tasks: list[DAGTask] = []
        self._names: set[str] = set()

    def task(
        self,
        task: BaseTask,
        name: str | None = None,
        depends_on: str | list[str] | None = None,
    ) -> DAGBuilder:
        """
        Add a task to the DAG.

        If depends_on is None, the task depends on the previously added task
        (sequential by default). depends_on=[] means the task is a DAG root.
        """
        task_name = name or f"task_{len(self._tasks)}"

        if task_name in self._names:
            raise ValueError(f"Duplicate task name: '{task_name}'")

        # Resolve depends_on
        if depends_on is None:
            # Sequential default: depend on previous task
            deps = [self._tasks[-1].name] if self._tasks else []
        elif isinstance(depends_on, str):
            deps = [depends_on]
        else:
            deps = list(depends_on)

        # Validate deps reference existing tasks
        for dep in deps:
            if dep not in self._names:
                raise ValueError(
                    f"Unknown dependency '{dep}' for task '{task_name}'. "
                    f"Available: {sorted(self._names)}"
                )

        self._names.add(task_name)
        self._tasks.append(DAGTask(name=task_name, task=task, depends_on=deps))
        return self

    def build(self) -> DAGDefinition:
        """Produce the immutable DAGDefinition."""
        if not self._tasks:
            raise ValueError(
                f"DAG '{self._name}' has no tasks. "
                "Add at least one task before calling .build()."
            )
        return DAGDefinition(
            name=self._name,
            schedule=self._schedule,
            tasks=list(self._tasks),
            description=self._description,
            tags=list(self._tags),
        )
