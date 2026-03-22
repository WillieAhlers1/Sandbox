"""SmartCompiler — auto-splits mixed pipelines into Airflow DAG + Vertex AI YAML.

Replaces the dual PipelineCompiler/DAGCompiler path with a unified compile step:
- Pure @ml_task → KFP YAML + thin DAG wrapper (same as today)
- Pure @task → DAG only, no YAML
- Mixed → DAG with operators + RunPipelineJobOperator(s) for ML groups
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

from gcp_ml_framework.config import Environment
from gcp_ml_framework.types import TaskType

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext
    from gcp_ml_framework.pipeline.builder import PipelineDefinition, PipelineStep


@dataclass
class CompilationResult:
    """Output of SmartCompiler.compile()."""

    dag_path: Path            # Generated Airflow DAG .py
    yaml_paths: list[Path] = field(default_factory=list)  # KFP YAML files (0 if pure @task)


@dataclass
class _StepGroup:
    """A consecutive run of steps sharing the same task_type."""

    task_type: TaskType
    steps: list[PipelineStep]
    index: int  # group ordinal for naming


class SmartCompiler:
    """Compile a unified Pipeline definition into deployable artifacts.

    The compiler analyzes task_type boundaries and produces:
    - One KFP YAML per ML_TASK group (delegated to PipelineCompiler)
    - One Airflow DAG file orchestrating everything
    """

    def __init__(
        self,
        output_dir: Path | str = "compiled_pipelines",
        dags_dir: Path | str = "dags",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.dags_dir = Path(dags_dir)

    def compile(
        self,
        pipeline_def: PipelineDefinition,
        context: MLContext,
        pipeline_dir: Path | None = None,
    ) -> CompilationResult:
        """Compile a pipeline definition to DAG + optional YAML files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.dags_dir.mkdir(parents=True, exist_ok=True)

        groups = self._group_steps(pipeline_def.steps)
        yaml_paths: list[Path] = []

        # Compile ML_TASK groups to KFP YAML
        for group in groups:
            if group.task_type == TaskType.ML_TASK:
                yaml_path = self._compile_ml_group(
                    group, pipeline_def, context, pipeline_dir
                )
                yaml_paths.append(yaml_path)

        # Generate the orchestrating Airflow DAG
        dag_path = self._generate_dag(
            groups, pipeline_def, context, yaml_paths, pipeline_dir
        )

        return CompilationResult(dag_path=dag_path, yaml_paths=yaml_paths)

    def _group_steps(self, steps: list[PipelineStep]) -> list[_StepGroup]:
        """Split steps into consecutive groups by task_type."""
        groups = []
        for i, (task_type, group_iter) in enumerate(
            groupby(steps, key=lambda s: s.task_type)
        ):
            groups.append(_StepGroup(
                task_type=task_type,
                steps=list(group_iter),
                index=i,
            ))
        return groups

    def _compile_ml_group(
        self,
        group: _StepGroup,
        pipeline_def: PipelineDefinition,
        context: MLContext,
        pipeline_dir: Path | None,
    ) -> Path:
        """Compile a group of ML_TASK steps to KFP YAML via PipelineCompiler."""
        from gcp_ml_framework.pipeline.builder import (
            PipelineDefinition as PipelineDef,
        )
        from gcp_ml_framework.pipeline.compiler import PipelineCompiler

        # Create a sub-pipeline definition for this group
        ml_groups = [
            g
            for g in self._group_steps(pipeline_def.steps)
            if g.task_type == TaskType.ML_TASK
        ]
        group_name = (
            pipeline_def.name
            if len(ml_groups) == 1
            else f"{pipeline_def.name}_ml_{group.index}"
        )

        sub_def = PipelineDef(
            name=group_name,
            schedule=pipeline_def.schedule,
            steps=group.steps,
            description=pipeline_def.description,
            tags=pipeline_def.tags,
        )

        compiler = PipelineCompiler(output_dir=self.output_dir)
        return compiler.compile(sub_def, context, pipeline_dir=pipeline_dir)

    def _generate_dag(
        self,
        groups: list[_StepGroup],
        pipeline_def: PipelineDefinition,
        context: MLContext,
        yaml_paths: list[Path],
        pipeline_dir: Path | None,
    ) -> Path:
        """Generate the Airflow DAG file."""
        dag_id = context.naming.dag_id(pipeline_def.name)
        dag_content = self._render_dag(
            groups, pipeline_def, context, yaml_paths, pipeline_dir
        )
        dag_path = self.dags_dir / f"{dag_id}.py"
        dag_path.write_text(dag_content)
        return dag_path

    def _render_dag(
        self,
        groups: list[_StepGroup],
        pipeline_def: PipelineDefinition,
        context: MLContext,
        yaml_paths: list[Path],
        pipeline_dir: Path | None,
    ) -> str:
        """Render the Python source of the Airflow DAG file."""
        dag_id = context.naming.dag_id(pipeline_def.name)
        description = pipeline_def.description or f"GML Pipeline: {pipeline_def.name}"

        if context.environment == Environment.DEV:
            schedule = "None"
        else:
            schedule = repr(pipeline_def.schedule)

        tags = [
            context.naming.team, context.naming.project, context.naming.branch
        ] + pipeline_def.tags

        imports: set[str] = set()
        task_blocks: list[str] = []
        task_names: list[str] = []
        yaml_index = 0

        for group in groups:
            if group.task_type == TaskType.ML_TASK:
                block, group_imports, name = self._render_ml_group(
                    group, pipeline_def, context, yaml_paths[yaml_index]
                )
                yaml_index += 1
                task_blocks.append(block)
                imports.update(group_imports)
                task_names.append(name)
            else:
                for step in group.steps:
                    block, step_imports, name = self._render_task_step(
                        step, context, pipeline_dir
                    )
                    task_blocks.append(block)
                    imports.update(step_imports)
                    task_names.append(name)

        # Generate sequential dependencies
        dep_lines = []
        for i in range(1, len(task_names)):
            dep_lines.append(f"{task_names[i - 1]} >> {task_names[i]}")

        imports_str = "\n".join(sorted(imports))
        tasks_str = "\n\n".join(task_blocks)
        deps_str = "\n    ".join(dep_lines) if dep_lines else ""

        has_vertex = any("RunPipelineJobOperator" in imp for imp in imports)
        template_fields_block = (
            "\n# Ensure Jinja macros in display_name/parameter_values"
            " are rendered\n"
            "RunPipelineJobOperator.template_fields = tuple(\n"
            "    dict.fromkeys(\n"
            "        (*RunPipelineJobOperator.template_fields,"
            ' "display_name", "parameter_values")\n'
            "    )\n"
            ")\n"
            if has_vertex
            else ""
        )

        return f'''\
"""
Auto-generated Airflow DAG: {pipeline_def.name}
Namespace: {context.namespace}
GCP project: {context.gcp_project}

DO NOT EDIT MANUALLY.
Regenerate with: gml compile
"""
from datetime import datetime, timedelta

from airflow import DAG
{imports_str}
{template_fields_block}
_default_args = {{
    "owner": "gcp-mlf",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": True,
    "email_on_retry": False,
}}

with DAG(
    dag_id="{dag_id}",
    description="{description}",
    schedule={schedule},
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags={tags!r},
    default_args=_default_args,
) as dag:

{textwrap.indent(tasks_str, "    ")}

    # --- Dependencies ---
    {deps_str}
'''

    def _render_ml_group(
        self,
        group: _StepGroup,
        pipeline_def: PipelineDefinition,
        context: MLContext,
        yaml_path: Path,
    ) -> tuple[str, set[str], str]:
        """Render an ML_TASK group as a RunPipelineJobOperator."""
        imports = {
            "from airflow.providers.google.cloud.operators"
            ".vertex_ai.pipeline_job"
            " import RunPipelineJobOperator",
        }

        ml_group_count = sum(
            1 for s in pipeline_def.steps if s.task_type == TaskType.ML_TASK
        )
        # Use a simple name if there's only one ML group
        if ml_group_count == len(pipeline_def.steps):
            task_id = "run_vertex_pipeline"
        else:
            task_id = f"run_vertex_pipeline_{group.index}"

        pipeline_name = yaml_path.stem
        template_path = (
            f"gs://{context.naming.gcs_bucket}/{context.naming.branch}"
            f"/pipelines/{pipeline_name}/pipeline.yaml"
        )
        pipeline_root = (
            f"gs://{context.naming.gcs_bucket}/{context.naming.branch}"
            f"/pipeline_runs/{pipeline_name}/"
        )
        service_account = context.pipeline_service_account

        code = f"""{task_id} = RunPipelineJobOperator(
    task_id="{task_id}",
    project_id="{context.gcp_project}",
    region="{context.region}",
    display_name="{pipeline_name}_{{{{ ds_nodash }}}}",
    template_path="{template_path}",
    pipeline_root="{pipeline_root}",
    enable_caching=False,
    deferrable=True,
    service_account="{service_account}",
    parameter_values={{"run_date": "{{{{ ds }}}}"}},
)"""
        return code, imports, task_id

    def _render_task_step(
        self,
        step: PipelineStep,
        context: MLContext,
        pipeline_dir: Path | None,
    ) -> tuple[str, set[str], str]:
        """Render a TASK step as a native Airflow operator."""
        component = step.component
        safe_name = step.name.replace(" ", "_").replace("-", "_").lower()

        if hasattr(component, "render_operator"):
            code_template, imports = component.render_operator(context, pipeline_dir=pipeline_dir)
            # Replace the {{ task_id }} placeholder
            code = code_template.replace("{{ task_id }}", safe_name)
            final_code = f"{safe_name} = {code}"
            return final_code, imports, safe_name

        # No render_operator — fail loud
        raise NotImplementedError(
            f"Component {type(component).__name__} is decorated with @task but does not "
            f"implement render_operator(). All @task components used in compiled pipelines "
            f"must implement render_operator() to generate native Airflow operator code. "
            f"Either add render_operator() to {type(component).__name__} or use a component "
            f"that already has it (e.g. BQQuery, BQTransform, Email)."
        )
