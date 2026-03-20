"""Structured logging setup for GCP ML Framework."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure structured JSON logging suitable for Cloud Logging."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='{"severity": "%(levelname)s", "message": "%(message)s", "logger": "%(name)s"}',
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"gcp_ml_framework.{name}")
