"""EvaluateModel — evaluate a trained model and apply metric gates."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from gcp_ml_framework.components.base import BaseComponent, ComponentConfig

if TYPE_CHECKING:
    from gcp_ml_framework.context import MLContext


@dataclass
class EvaluateModel(BaseComponent):
    """
    Evaluate a model against a held-out dataset and apply metric gates.

    If any gate threshold is not met, the component raises an exception which
    halts the KFP pipeline (preventing deployment of a poor model).

    Example:
        EvaluateModel(
            metrics=["auc", "f1"],
            gate={"auc": 0.75},      # pipeline fails if auc < 0.75
        )
    """

    metrics: list[str] = field(default_factory=lambda: ["auc"])
    gate: dict[str, float] = field(default_factory=dict)
    component_name: str = "evaluate_model"
    config: ComponentConfig = field(default_factory=ComponentConfig)

    def as_kfp_component(self, base_image: str | None = None):
        from kfp import dsl  # type: ignore[import]

        image = base_image or "python:3.11-slim"
        # scikit-learn is an ML package NOT included in the component-base image,
        # so it must always be installed.
        if base_image:
            pkgs = ["scikit-learn>=1.4"]
        else:
            pkgs = [
                "scikit-learn>=1.4",
                "google-cloud-bigquery>=3.17",
                "google-cloud-storage>=2.14",
                "google-cloud-aiplatform>=1.49",
                "pandas>=2",
                "db-dtypes>=1.2",
            ]

        @dsl.component(
            base_image=image,
            packages_to_install=pkgs,
        )
        def evaluate_model(
            model_uri: str,
            eval_dataset_uri: str,
            metrics: str,       # JSON list
            gate: str,          # JSON dict
            experiment_name: str,
            project: str,
            region: str,
        ) -> str:
            """Returns JSON string of computed metric values. Raises on gate failure."""
            import json
            import pickle
            import tempfile

            from google.cloud import bigquery, storage
            from sklearn.metrics import f1_score, roc_auc_score

            metric_names = json.loads(metrics)
            gate_thresholds = json.loads(gate)

            # Read eval dataset from BigQuery (eval_dataset_uri is a fully-qualified table)
            bq_client = bigquery.Client(project=project)
            df = bq_client.query(f"SELECT * FROM `{eval_dataset_uri}`").to_dataframe()
            print(f"Loaded {len(df)} rows from {eval_dataset_uri}")

            X = df.drop(columns=["label", "user_id", "feature_timestamp"], errors="ignore")
            y = df["label"]

            # Download model.pkl from GCS to a local temp file
            parts = model_uri.replace("gs://", "").split("/", 1)
            bucket_name = parts[0]
            blob_path = (parts[1] + "/model.pkl") if len(parts) > 1 else "model.pkl"
            gcs_client = storage.Client(project=project)
            blob = gcs_client.bucket(bucket_name).blob(blob_path)
            with tempfile.NamedTemporaryFile(suffix=".pkl") as tmp:
                blob.download_to_filename(tmp.name)
                with open(tmp.name, "rb") as f:
                    model = pickle.load(f)
            print(f"Loaded model from {model_uri}/model.pkl")

            # Compute real metrics
            computed: dict = {}
            proba = model.predict_proba(X)[:, 1] if hasattr(model, "predict_proba") else model.predict(X)
            preds = (proba > 0.5).astype(int)

            if "auc" in metric_names:
                computed["auc"] = round(float(roc_auc_score(y, proba)), 4)
            if "f1" in metric_names:
                computed["f1"] = round(float(f1_score(y, preds)), 4)
            print(f"Metrics: {computed}")

            # Apply gates
            failures = []
            for metric, threshold in gate_thresholds.items():
                if metric in computed and computed[metric] < threshold:
                    failures.append(f"{metric}={computed[metric]:.4f} < threshold={threshold}")

            if failures:
                raise ValueError(f"Model failed evaluation gates: {', '.join(failures)}")

            # Log metrics to Vertex AI Experiments (best-effort — don't fail the pipeline)
            try:
                import hashlib
                from google.cloud import aiplatform
                aiplatform.init(project=project, location=region, experiment=experiment_name)
                run_id = "eval-" + hashlib.md5(model_uri.encode()).hexdigest()[:8]
                aiplatform.start_run(run=run_id)
                aiplatform.log_metrics(computed)
                aiplatform.end_run()
                print(f"Logged metrics to experiment '{experiment_name}' run '{run_id}': {computed}")
            except Exception as e:
                print(f"Warning: could not log to experiments: {e}")

            return json.dumps(computed)

        return evaluate_model

    def local_run(
        self,
        context: "MLContext",
        model_path: str = "",
        eval_dataset_path: str = "",
        **kwargs: Any,
    ) -> dict[str, float]:
        """Return deterministic placeholder metric values locally."""
        _placeholder = {"auc": 0.50, "f1": 0.50, "accuracy": 0.50, "precision": 0.50, "recall": 0.50}
        computed = {m: _placeholder.get(m, 0.50) for m in self.metrics}
        print(f"[local] EvaluateModel: metrics={computed} (placeholder — no model loaded)")

        failures = [
            f"{m}={v:.4f} < {self.gate[m]}"
            for m, v in computed.items()
            if m in self.gate and v < self.gate[m]
        ]
        if failures:
            raise ValueError(f"[local] Gate failures: {', '.join(failures)}")

        return computed
