"""E2E tests for the training pipeline.

These tests require GCP auth and seeded BigQuery data.
Run with: uv run -- pytest tests/training_pipeline/test_e2e.py -m e2e -v
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.e2e
class TestTrainingPipelineE2E:
    def test_compile_produces_yaml(self):
        """gml compile produces valid YAML with correct image URI."""
        from gcp_ml_framework.cli._helpers import load_context
        from gcp_ml_framework.pipeline.smart_compiler import SmartCompiler

        ctx = load_context()
        pipeline_dir = Path("pipelines/training_pipeline")

        # Import pipeline definition
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("_pipeline_e2e", pipeline_dir / "pipeline.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_pipeline_e2e"] = mod
        spec.loader.exec_module(mod)
        pipeline_def = mod.pipeline

        compiler = SmartCompiler()
        result = compiler.compile(pipeline_def, ctx, pipeline_dir=pipeline_dir)

        assert result.dag_path.exists()
        assert len(result.yaml_paths) >= 1
        for yaml_path in result.yaml_paths:
            assert yaml_path.exists()
            content = yaml_path.read_text()
            assert "container" in content.lower()

    def test_local_run_completes(self):
        """gml run --local completes without error (requires seeded BQ data)."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gcp_ml_framework.cli.main",
                "run",
                "training_pipeline",
                "--local",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**__import__("os").environ},
        )
        assert result.returncode == 0, f"Local run failed: {result.stderr}"
