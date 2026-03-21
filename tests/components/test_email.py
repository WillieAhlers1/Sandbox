"""Unit tests for Email component (gcp_ml_framework.components.operators.email)."""

from __future__ import annotations

import pytest

from gcp_ml_framework.components.operators.email import Email
from gcp_ml_framework.decorators import TaskType

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Instantiation and task type
# ---------------------------------------------------------------------------


class TestEmailBasics:
    def test_is_task_type(self):
        assert Email._task_type == TaskType.TASK

    def test_instantiation(self):
        email = Email(to=["alice@example.com"], subject="Test")
        assert email.to == ["alice@example.com"]
        assert email.subject == "Test"
        assert email.component_name == "email"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestEmailValidation:
    def test_requires_recipients(self):
        with pytest.raises(ValueError, match="at least one recipient"):
            Email(subject="Test")


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------


class TestEmailResolve:
    def test_resolve_subject(self, mock_context):
        email = Email(to=["a@b.com"], subject="Pipeline {namespace} done")
        resolved = email.resolve_subject(mock_context)
        assert mock_context.namespace in resolved
        assert "{namespace}" not in resolved

    def test_resolve_body(self, mock_context):
        email = Email(to=["a@b.com"], subject="Test", body="Data in {bq_dataset}")
        resolved = email.resolve_body(mock_context)
        assert mock_context.bq_dataset in resolved
