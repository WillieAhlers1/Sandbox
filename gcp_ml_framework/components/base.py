"""
BaseComponent — abstract base class for all framework pipeline components.

Every built-in and custom component implements this interface. The key
methods are:

    as_kfp_component()    → returns the @dsl.container_component-decorated KFP function
    cli()                 → classmethod, Typer-based CLI entrypoint for container execution
    execute()             → container lifecycle (override in subclasses for I/O management)
    run()                 → business logic (data scientists override this in step subclasses)

Components are Pydantic models. Data scientists subclass them to add a run() method.
The execute() lifecycle wraps run() with I/O (GCS upload/download, temp dirs, etc.).
"""

import inspect
import json
from collections.abc import Callable
from typing import Any, ClassVar

from pydantic_core import PydanticUndefined
from pydantic_settings import BaseSettings, SettingsConfigDict
from gcp_ml_framework.types import TaskType

# Fields that are never exposed as CLI flags or KFP params
_INTERNAL_FIELDS = frozenset({
    "component_name", "component_version", "timeout_seconds", "retry_count", "cache_enabled",
    "runtime_dockerfile", "serving_dockerfile", "model_name", "gcp_config",
})

# Fields excluded from KFP input params (output_uri_path is handled via dsl.OutputPath)
_KFP_EXCLUDED_FIELDS = _INTERNAL_FIELDS | {"output_uri_path"}


class BaseComponent(BaseSettings):
    """
    Abstract base for all GCP ML Framework pipeline components.

    Data scientists subclass a component and override run() for business logic.
    The component's execute() method wraps run() with I/O lifecycle (temp dirs,
    GCS upload/download, writing output URIs).

    Every Pydantic field (except _INTERNAL_FIELDS) becomes a first-class CLI flag
    and KFP input parameter — no JSON blob.
    """

    model_config = SettingsConfigDict(arbitrary_types_allowed=True)

    # --- Task type (set by @task / @ml_task decorators) ---
    task_type: ClassVar[TaskType] = TaskType.TASK

    # --- Internal fields (not passed as params) ---
    component_name: str = ""
    component_version: str = "v1"
    timeout_seconds: int = 3600
    retry_count: int = 1
    cache_enabled: bool = True
    # Path to the Dockerfile this component executes in, relative to docker/.
    # Example: "pipelines/house_price/train.Dockerfile"
    # Required — every component must explicitly declare its runtime image.
    # The stem (filename without .Dockerfile) is extracted internally for image
    # naming via NamingConvention.docker_image_uri().
    runtime_dockerfile: str

    # --- Resource fields ---
    machine_type: str = "n2-standard-4"
    accelerator_type: str = ""
    accelerator_count: int = 0

    # --- Universal params (present on every component) ---
    project: str = ""
    region: str = "us-central1"
    project_name: str = ""
    branch: str = ""
    environment: str = ""
    output_uri_path: str = ""
    run_date: str = ""
    dataset: str = ""


    
    @classmethod
    def cli(cls) -> None:
        """Typer-based CLI entrypoint for container execution.

        Auto-generates a --flag for every Pydantic field (except _INTERNAL_FIELDS).
        Non-string types (dict, list) are passed as JSON strings and parsed before
        Pydantic instantiation.
        """
        import typer

        app = typer.Typer()

        # Build dynamic signature from model_fields
        sig_params = []
        for name, field_info in cls.model_fields.items():
            if name in _INTERNAL_FIELDS:
                continue
            default = field_info.default
            if default is PydanticUndefined:
                opt = typer.Option("", help=name)
            else:
                opt = typer.Option(
                    str(default) if not isinstance(default, str) else default,
                    help=name,
                )
            sig_params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=opt,
                    annotation=str,
                )
            )

        def _run(**kwargs):
            from loguru import logger

            # Parse JSON strings back to dicts/lists for Pydantic
            parsed = {}
            for k, v in kwargs.items():
                if isinstance(v, str) and v and v[0] in ("{", "["):
                    try:
                        v = json.loads(v)
                    except (json.JSONDecodeError, ValueError):
                        pass
                parsed[k] = v

            logger.info(f"[cli] Instantiating {cls.__name__} with params: {parsed}")
            instance = cls(**parsed)

            logger.info(f"[cli] Calling {cls.__name__}.execute()")
            instance.execute()
            logger.info(f"[cli] {cls.__name__} completed")

        _run.__signature__ = inspect.Signature(sig_params)
        app.command()(_run)
        app()

    def execute(self) -> None:
        """Container lifecycle method. Override in component subclasses for I/O management.

        Default implementation delegates directly to run().
        Component subclasses (e.g. TrainModel) override this to add temp dirs,
        GCS upload/download, and output URI writing around the run() call.
        """
        self.run()

    def run(self) -> Any:
        """Business logic — data scientists override this in step subclasses.

        All params are available as self.<field_name>.
        The component's execute() method handles I/O lifecycle around this call.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.run() is not implemented. "
            "Override this method in your step subclass."
        )

    def as_kfp_component(
        self,
        step_module: str,
        base_image: str | None = None,
    ) -> Callable:
        """Return a @dsl.container_component with first-class params from model_fields.

        Each Pydantic field (except _INTERNAL_FIELDS) becomes a KFP str input.
        output_uri_path is handled specially via dsl.OutputPath.

        Args:
            step_module: Dotted module path
                (e.g. "pipelines.training_pipeline.steps.train_house_model").
            base_image: Pre-built Docker image. Falls back to python:3.12-slim.
        """
        from kfp import dsl

        image = base_image or "python:3.12-slim"

        # Collect param names from model_fields (skip _KFP_EXCLUDED_FIELDS)
        param_names = [n for n in type(self).model_fields if n not in _KFP_EXCLUDED_FIELDS]

        # All param names in order: model fields + output_uri (KFP output artifact)
        all_names = param_names + ["output_uri"]

        # Build inspect.Signature: all str params + output_uri
        sig_params = [
            inspect.Parameter(
                n, inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default="", annotation=str,
            )
            for n in param_names
        ]
        sig_params.append(
            inspect.Parameter(
                "output_uri",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default="",
                annotation=dsl.OutputPath(str),
            )
        )

        def _component_fn(*args) -> dsl.ContainerSpec:
            # Map positional args to named params (KFP calls with *arg_list)
            kwargs = dict(zip(all_names, args))
            cli_args = []
            for name in param_names:
                flag = "--" + name.replace("_", "-")
                cli_args.extend([flag, kwargs.get(name, "")])
            cli_args.extend(["--output-uri-path", kwargs.get("output_uri", "")])
            return dsl.ContainerSpec(
                image=image,
                command=["python", "-m", step_module],
                args=cli_args,
            )

        _component_fn.__name__ = self.component_name or self.__class__.__name__
        _component_fn.__signature__ = inspect.Signature(sig_params)
        return dsl.container_component(_component_fn)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.component_name!r})"
