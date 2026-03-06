"""
BaseComponent — abstract base class for all framework pipeline components.

Every built-in and custom component implements this interface. The two key
methods are:

    as_kfp_component()    → returns the @dsl.component-decorated KFP function
    local_run()           → runs the component logic locally (DuckDB/pandas stubs)

Components are pure data classes — they carry configuration, not state.
The actual execution logic lives inside the KFP component function body.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class ComponentConfig:
    """Per-component resource configuration, applied as KFP resource specs."""

    machine_type: str = "n2-standard-4"
    accelerator_type: str | None = None
    accelerator_count: int = 0
    timeout_seconds: int = 3600
    retry_count: int = 1
    cache_enabled: bool = True


class BaseComponent(ABC):
    """
    Abstract base for all GCP ML Framework pipeline components.

    Subclasses must implement:
        - as_kfp_component(): return the @dsl.component function
        - local_run(): execute component logic without GCP

    """

    # Subclasses should override these
    component_name: str = ""
    component_version: str = "v1"
    config: ComponentConfig = field(default_factory=ComponentConfig)  # type: ignore[assignment]

    @abstractmethod
    def as_kfp_component(self, base_image: str | None = None) -> Callable:
        """Return the @dsl.component-decorated KFP v2 function.

        Args:
            base_image: Pre-built Docker image with all dependencies installed.
                When provided, the component uses this image and skips
                packages_to_install. When None, falls back to python:3.11-slim
                with runtime pip install (slower but requires no pre-built image).
        """
        ...

    @abstractmethod
    def local_run(self, context: MLContext, **kwargs: Any) -> Any:
        """
        Execute this component locally without GCP access.

        Used by LocalRunner for fast iteration. DuckDB, pandas, and in-memory
        Feature Store stubs replace real GCP SDK calls.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.component_name!r})"
