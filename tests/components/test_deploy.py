"""Unit tests for DeployModel (gcp_ml_framework.components.ml.deploy)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gcp_ml_framework.components.base import BaseComponent
from gcp_ml_framework.components.ml.deploy import DeployModel

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestDeployModelInstantiation:
    """Verify DeployModel fields, defaults, and overrides."""

    def test_deploy_model_instantiation(self):
        """DeployModel creates with endpoint_name (required) and sensible defaults."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert isinstance(dm, BaseComponent)
        assert dm.endpoint_name == "churn-v1"
        assert dm.model_uri == ""
        assert dm.model_display_name == ""
        assert dm.endpoint_display_name == ""
        assert dm.serving_container_image == ""
        assert dm.component_name == "deploy_model"

    def test_deploy_model_machine_type_override(self):
        """DeployModel defaults machine_type to n2-standard-2, overriding BaseComponent."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert dm.machine_type == "n2-standard-2"
        # Confirm base default is different
        base = BaseComponent()
        assert base.machine_type == "n2-standard-4"

    def test_deploy_model_traffic_split_default(self):
        """traffic_split defaults to {"new": 100}."""
        dm = DeployModel(endpoint_name="churn-v1")
        assert dm.traffic_split == {"new": 100}


# ---------------------------------------------------------------------------
# execute() delegation
# ---------------------------------------------------------------------------


class TestDeployModelExecute:
    """Verify execute() delegates to utils.vertex.run_deploy with correct args."""

    @patch("gcp_ml_framework.utils.vertex.run_deploy")
    def test_deploy_model_execute_delegates(self, mock_run_deploy: MagicMock):
        """execute() calls run_deploy() with all the component's field values."""
        dm = DeployModel(
            endpoint_name="churn-v1",
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            endpoint_display_name="churn-endpoint",
            serving_container_image="gcr.io/proj/serving:v1",
            machine_type="n2-standard-4",
            min_replica_count=2,
            max_replica_count=5,
            traffic_split={"new": 50, "current": 50},
            output_uri_path="/tmp/output_uri",
        )
        dm.execute()

        mock_run_deploy.assert_called_once_with(
            project="test-project",
            region="us-east1",
            model_uri="gs://bucket/model",
            model_display_name="churn-model",
            endpoint_display_name="churn-endpoint",
            serving_container_image="gcr.io/proj/serving:v1",
            machine_type="n2-standard-4",
            min_replica_count=2,
            max_replica_count=5,
            traffic_split={"new": 50, "current": 50},
            output_uri_path="/tmp/output_uri",
        )
