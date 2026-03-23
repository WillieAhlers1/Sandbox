"""Verify all pipeline definitions use correct component API."""

import pytest

pytestmark = pytest.mark.unit


def test_all_pipeline_deploy_steps_use_model_name():
    """All DeployModel steps must use model_name, not removed endpoint_name."""
    from pipelines.house_price.pipeline import pipeline as hp
    from pipelines.training_pipeline.pipeline import pipeline as tp
    from pipelines.verification_pipeline.pipeline import pipeline as vp

    for name, p in [("house_price", hp), ("training", tp), ("verification", vp)]:
        for step in p.steps:
            if step.component.__class__.__name__ == "DeployModel":
                assert step.component.model_name != "", (
                    f"{name} pipeline: DeployModel.model_name is empty — "
                    "likely using removed endpoint_name field"
                )


def test_no_endpoint_name_in_pipeline_source():
    """Pipeline source files must not contain endpoint_name= (removed field)."""
    from pathlib import Path

    for pipeline_dir in ["training_pipeline", "verification_pipeline", "house_price"]:
        pipeline_file = Path("pipelines") / pipeline_dir / "pipeline.py"
        if pipeline_file.exists():
            content = pipeline_file.read_text()
            assert "endpoint_name=" not in content, (
                f"{pipeline_file}: still uses removed endpoint_name= field"
            )
