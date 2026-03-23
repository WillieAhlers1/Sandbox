"""Unit tests for BaseComponent (gcp_ml_framework.components.base)."""

from __future__ import annotations

import inspect

import pytest

from gcp_ml_framework.components.base import _INTERNAL_FIELDS, BaseComponent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Flat resource fields
# ---------------------------------------------------------------------------


class TestBaseComponentFlatResourceFields:
    """Verify that resource fields live directly on BaseComponent (no ComponentConfig)."""

    def test_base_component_has_flat_resource_fields(self):
        """machine_type, accelerator_type, accelerator_count are direct model fields."""
        comp = BaseComponent()
        assert hasattr(comp, "machine_type")
        assert hasattr(comp, "accelerator_type")
        assert hasattr(comp, "accelerator_count")
        # They should be declared in model_fields, not nested inside a sub-model
        assert "machine_type" in BaseComponent.model_fields
        assert "accelerator_type" in BaseComponent.model_fields
        assert "accelerator_count" in BaseComponent.model_fields

    def test_base_component_defaults(self):
        """Verify default values for all resource and internal fields."""
        comp = BaseComponent()
        # Resource defaults
        assert comp.machine_type == "n2-standard-4"
        assert comp.accelerator_type == ""
        assert comp.accelerator_count == 0
        # Internal defaults
        assert comp.timeout_seconds == 3600
        assert comp.retry_count == 1
        assert comp.cache_enabled is False
        assert comp.component_name == ""
        assert comp.component_version == "v1"
        # Universal param defaults
        assert comp.project == ""
        assert comp.region == "us-central1"


# ---------------------------------------------------------------------------
# _INTERNAL_FIELDS
# ---------------------------------------------------------------------------


class TestInternalFields:
    """Verify the _INTERNAL_FIELDS set contains exactly the expected entries."""

    def test_internal_fields_set(self):
        """_INTERNAL_FIELDS contains the expected entries and NOT resource fields."""
        expected = {
            "component_name",
            "component_version",
            "timeout_seconds",
            "retry_count",
            "cache_enabled",
            "runtime_dockerfile",
            "serving_dockerfile",
            "model_name",
        }
        assert _INTERNAL_FIELDS == expected
        assert "machine_type" not in _INTERNAL_FIELDS
        assert "accelerator_type" not in _INTERNAL_FIELDS
        assert "accelerator_count" not in _INTERNAL_FIELDS

    def test_internal_fields_all_exist_on_some_component(self):
        """Every _INTERNAL_FIELDS entry must be a field on BaseComponent or a subclass."""
        from gcp_ml_framework.components.ml.deploy import DeployModel
        from gcp_ml_framework.components.ml.register import RegisterModel

        all_fields: set[str] = set()
        for cls in (BaseComponent, RegisterModel, DeployModel):
            all_fields.update(cls.model_fields.keys())

        for field_name in _INTERNAL_FIELDS:
            assert field_name in all_fields, (
                f"_INTERNAL_FIELDS contains '{field_name}' which is not a field "
                "on BaseComponent, RegisterModel, or DeployModel"
            )


# ---------------------------------------------------------------------------
# ComponentConfig removed
# ---------------------------------------------------------------------------


class TestComponentConfigRemoved:
    """Ensure the old ComponentConfig class is no longer importable."""

    def test_component_config_not_importable(self):
        """Importing ComponentConfig from base raises ImportError."""
        with pytest.raises(ImportError):
            from gcp_ml_framework.components.base import ComponentConfig  # noqa: F401


# ---------------------------------------------------------------------------
# CLI excludes internal fields
# ---------------------------------------------------------------------------


class TestCLI:
    """Verify that cli() builds a Typer signature that excludes internal fields."""

    def test_cli_excludes_internal_fields(self):
        """The dynamic signature built by cli() should skip _INTERNAL_FIELDS."""
        # We don't invoke Typer; we replicate the signature-building logic from cli()
        # and verify the resulting parameter names exclude internal fields.
        from pydantic_core import PydanticUndefined

        sig_params = []
        for name, field_info in BaseComponent.model_fields.items():
            if name in _INTERNAL_FIELDS:
                continue
            default = field_info.default
            sig_params.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=default if default is not PydanticUndefined else "",
                    annotation=str,
                )
            )

        sig = inspect.Signature(sig_params)
        param_names = set(sig.parameters.keys())

        for internal in _INTERNAL_FIELDS:
            assert internal not in param_names, f"{internal} should be excluded from CLI"

        # Resource fields SHOULD be present (they are not internal)
        assert "machine_type" in param_names
        assert "accelerator_type" in param_names
        assert "accelerator_count" in param_names


# ---------------------------------------------------------------------------
# run() and execute()
# ---------------------------------------------------------------------------


class TestRunAndExecute:
    """Verify run()/execute() contract on the base class."""

    def test_run_raises_not_implemented(self):
        """BaseComponent().run() raises NotImplementedError with a helpful message."""
        comp = BaseComponent()
        with pytest.raises(NotImplementedError, match="BaseComponent.run\\(\\) is not implemented"):
            comp.run()

    def test_execute_calls_run(self):
        """BaseComponent.execute() delegates to run()."""
        run_called = False

        class _Stub(BaseComponent):
            def run(self) -> None:
                nonlocal run_called
                run_called = True

        comp = _Stub()
        comp.execute()
        assert run_called, "execute() should have called run()"


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    """Verify the repr format includes class name and component_name."""

    def test_repr(self):
        """repr includes class name and component_name."""
        comp = BaseComponent(component_name="my_step")
        result = repr(comp)
        assert "BaseComponent" in result
        assert "my_step" in result
