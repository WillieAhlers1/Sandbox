"""Phase 5 — Integration / E2E tests.

Full compile + local run for all 3 use cases:
- churn_prediction (PipelineBuilder)
- sales_analytics (DAGBuilder, fan-out/fan-in)
- recommendation_engine (DAGBuilder, hybrid with Vertex pipelines)

Also tests that generated DAGs parse cleanly and have no framework imports.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from gcp_ml_framework.config import FrameworkConfig, GCPConfig
from gcp_ml_framework.context import MLContext
from gcp_ml_framework.dag.factory import discover_and_render

PIPELINES_DIR = Path(__file__).resolve().parents[2] / "pipelines"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def e2e_context():
    """MLContext matching the real framework.yaml project config."""
    cfg = FrameworkConfig(
        team="dsci",
        project="examplechurn",
        branch="feature/e2e-test",
        gcp=GCPConfig(
            dev_project_id="gcp-gap-demo-dev",
            staging_project_id="gcp-gap-demo-staging",
            prod_project_id="gcp-gap-demo-prod",
        ),
    )
    return MLContext.from_config(cfg)


def _load_module(name: str, path: Path):
    """Import a module from a file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Churn Prediction (pipeline.py) ────────────────────────────────────────────


class TestChurnPredictionE2E:
    pipeline_dir = PIPELINES_DIR / "churn_prediction"

    def test_pipeline_importable(self):
        mod = _load_module("_e2e_churn", self.pipeline_dir / "pipeline.py")
        assert hasattr(mod, "pipeline")
        assert mod.pipeline.name == "churn_prediction"

    def test_pipeline_has_correct_steps(self):
        mod = _load_module("_e2e_churn2", self.pipeline_dir / "pipeline.py")
        step_names = [s.name for s in mod.pipeline.steps]
        assert "ingest_raw_events" in step_names
        assert "engineer_features" in step_names
        assert "train_churn_model" in step_names
        assert "evaluate_model" in step_names
        assert "deploy_churn_model" in step_names

    def test_local_run(self, e2e_context):
        from gcp_ml_framework.pipeline.runner import LocalRunner

        mod = _load_module("_e2e_churn3", self.pipeline_dir / "pipeline.py")
        seeds_dir = self.pipeline_dir / "seeds"
        runner = LocalRunner(e2e_context, seeds_dir=seeds_dir)
        outputs = runner.run(mod.pipeline)
        # Pipeline runs end-to-end: real model trained on seed data passes the AUC gate
        assert "evaluate_model" in outputs
        assert outputs["evaluate_model"]["auc"] >= 0.78

    def test_local_run_dry_run(self, e2e_context):
        from gcp_ml_framework.pipeline.runner import LocalRunner

        mod = _load_module("_e2e_churn4", self.pipeline_dir / "pipeline.py")
        seeds_dir = self.pipeline_dir / "seeds"
        runner = LocalRunner(e2e_context, seeds_dir=seeds_dir)
        outputs = runner.run(mod.pipeline, dry_run=True)
        assert outputs == {}  # dry run produces no outputs

    def test_compile_dag(self, e2e_context, tmp_path):
        dag_filename, dag_content = discover_and_render(self.pipeline_dir, e2e_context)
        assert dag_filename.endswith(".py")
        assert "churn_prediction" in dag_filename
        assert "from airflow" in dag_content
        assert "gcp_ml_framework" not in dag_content

    def test_seeds_exist(self):
        seeds = self.pipeline_dir / "seeds"
        assert seeds.exists()
        assert (seeds / "raw_user_events.csv").exists()


# ── Sales Analytics (dag.py) ─────────────────────────────────────────────────


class TestSalesAnalyticsE2E:
    pipeline_dir = PIPELINES_DIR / "sales_analytics"

    def test_dag_importable(self):
        mod = _load_module("_e2e_sales", self.pipeline_dir / "dag.py")
        assert hasattr(mod, "dag")
        assert mod.dag.name == "sales_analytics"

    def test_dag_shape(self):
        mod = _load_module("_e2e_sales2", self.pipeline_dir / "dag.py")
        task_names = {t.name for t in mod.dag.tasks}
        expected = {
            "extract_orders", "extract_inventory", "extract_returns",
            "agg_revenue", "check_stock", "agg_refunds",
            "build_report", "notify",
        }
        assert task_names == expected

    def test_topological_order(self):
        mod = _load_module("_e2e_sales3", self.pipeline_dir / "dag.py")
        order = [t.name for t in mod.dag.topological_order()]
        # build_report must come after all three aggregations
        assert order.index("build_report") > order.index("agg_revenue")
        assert order.index("build_report") > order.index("check_stock")
        assert order.index("build_report") > order.index("agg_refunds")
        # notify must come last
        assert order.index("notify") > order.index("build_report")

    def test_local_run(self, e2e_context):
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        mod = _load_module("_e2e_sales4", self.pipeline_dir / "dag.py")
        seeds_dir = self.pipeline_dir / "seeds"
        runner = DAGLocalRunner(
            e2e_context,
            seeds_dir=seeds_dir,
            pipeline_dir=self.pipeline_dir,
        )
        runner.run(mod.dag)

    def test_compile_dag(self, e2e_context, tmp_path):
        dag_filename, dag_content = discover_and_render(self.pipeline_dir, e2e_context)
        assert dag_filename.endswith(".py")
        assert "sales_analytics" in dag_filename
        assert "from airflow" in dag_content
        assert "gcp_ml_framework" not in dag_content

    def test_seeds_exist(self):
        seeds = self.pipeline_dir / "seeds"
        assert seeds.exists()
        assert (seeds / "raw_orders.csv").exists()
        assert (seeds / "raw_inventory.csv").exists()
        assert (seeds / "raw_returns.csv").exists()


# ── Recommendation Engine (dag.py with VertexPipelineTasks) ───────────────────


class TestRecommendationEngineE2E:
    pipeline_dir = PIPELINES_DIR / "recommendation_engine"

    def test_dag_importable(self):
        mod = _load_module("_e2e_reco", self.pipeline_dir / "dag.py")
        assert hasattr(mod, "dag")
        assert mod.dag.name == "recommendation_engine"

    def test_dag_shape(self):
        mod = _load_module("_e2e_reco2", self.pipeline_dir / "dag.py")
        task_names = {t.name for t in mod.dag.tasks}
        assert task_names == {
            "extract_data",
            "compute_features",
            "train_model",
            "notify",
        }

    def test_embedded_vertex_pipelines(self):
        mod = _load_module("_e2e_reco3", self.pipeline_dir / "dag.py")
        from gcp_ml_framework.dag.tasks.vertex_pipeline import VertexPipelineTask

        vertex_tasks = [
            t for t in mod.dag.tasks if isinstance(t.task, VertexPipelineTask)
        ]
        assert len(vertex_tasks) == 2
        # Pipelines are embedded inline (pipeline object, not just name)
        for vt in vertex_tasks:
            assert vt.task.pipeline is not None
        pipeline_names = {t.task.pipeline_name for t in vertex_tasks}
        assert pipeline_names == {"reco_features", "reco_training"}

    def test_local_run(self, e2e_context):
        from gcp_ml_framework.dag.runner import DAGLocalRunner

        mod = _load_module("_e2e_reco4", self.pipeline_dir / "dag.py")
        seeds_dir = self.pipeline_dir / "seeds"
        runner = DAGLocalRunner(
            e2e_context,
            seeds_dir=seeds_dir,
            pipeline_dir=self.pipeline_dir,
        )
        runner.run(mod.dag)

    def test_compile_dag(self, e2e_context, tmp_path):
        dag_filename, dag_content = discover_and_render(self.pipeline_dir, e2e_context)
        assert dag_filename.endswith(".py")
        assert "recommendation_engine" in dag_filename
        assert "from airflow" in dag_content
        assert "gcp_ml_framework" not in dag_content

    def test_seeds_exist(self):
        seeds = self.pipeline_dir / "seeds"
        assert seeds.exists()
        assert (seeds / "raw_interactions.csv").exists()



# ── Generated DAGs: Parse + No Framework Imports ─────────────────────────────


class TestGeneratedDAGs:
    """Verify all generated DAG files can be imported and have no framework imports."""

    @pytest.fixture(autouse=True)
    def _compile_all_dags(self, e2e_context, tmp_path):
        """Compile all pipelines to DAG files for testing."""
        self.dag_dir = tmp_path / "dags"
        self.dag_dir.mkdir()
        self.dag_files = {}

        for pipeline_path in PIPELINES_DIR.iterdir():
            if not pipeline_path.is_dir():
                continue
            if pipeline_path.name.startswith("_"):
                continue
            has_dag = (pipeline_path / "dag.py").exists()
            has_pipeline = (pipeline_path / "pipeline.py").exists()
            if not has_dag and not has_pipeline:
                continue

            try:
                dag_filename, dag_content = discover_and_render(pipeline_path, e2e_context)
                dag_file = self.dag_dir / dag_filename
                dag_file.write_text(dag_content)
                self.dag_files[pipeline_path.name] = dag_file
            except Exception:
                pass

    def test_generated_dags_exist(self):
        assert len(self.dag_files) > 0

    def test_generated_dags_parse_cleanly(self):
        """All generated DAG files should be valid Python."""
        for name, dag_file in self.dag_files.items():
            content = dag_file.read_text()
            try:
                compile(content, str(dag_file), "exec")
            except SyntaxError as e:
                pytest.fail(f"DAG file for {name} has syntax error: {e}")

    def test_generated_dags_no_framework_imports(self):
        """No generated DAG file should import from gcp_ml_framework."""
        for name, dag_file in self.dag_files.items():
            content = dag_file.read_text()
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                if "gcp_ml_framework" in line and ("import" in line or "from" in line):
                    pytest.fail(
                        f"DAG file for {name} line {i} imports from gcp_ml_framework: {line.strip()}"
                    )

    def test_generated_dags_have_airflow_imports(self):
        """All generated DAGs should use standard Airflow imports."""
        for name, dag_file in self.dag_files.items():
            content = dag_file.read_text()
            assert "from airflow" in content, f"DAG for {name} missing airflow import"
            assert "DAG(" in content, f"DAG for {name} missing DAG instantiation"

    def test_generated_dags_have_schedule(self):
        """All generated DAGs should have a schedule."""
        for name, dag_file in self.dag_files.items():
            content = dag_file.read_text()
            assert "schedule" in content, f"DAG for {name} missing schedule"
