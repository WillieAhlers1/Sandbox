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

    def as_kfp_component(self):
        from kfp import dsl  # type: ignore[import]

        @dsl.component(
            base_image="python:3.11-slim",
            packages_to_install=[
                "scikit-learn>=1.4",
                "pandas>=2",
                "pyarrow>=15",
                "google-cloud-aiplatform>=1.49",
            ],
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

            import pandas as pd
            from sklearn.metrics import f1_score, roc_auc_score

            metric_names = json.loads(metrics)
            gate_thresholds = json.loads(gate)

            df = pd.read_parquet(eval_dataset_uri)
            X, y = df.drop("label", axis=1), df["label"]

            with open(f"{model_uri}/model.pkl", "rb") as f:
                model = pickle.load(f)

            computed: dict = {}
            proba = model.predict_proba(X)[:, 1] if hasattr(model, "predict_proba") else model.predict(X)
            preds = (proba > 0.5).astype(int)

            if "auc" in metric_names:
                computed["auc"] = float(roc_auc_score(y, proba))
            if "f1" in metric_names:
                computed["f1"] = float(f1_score(y, preds))

            # Apply gates
            failures = []
            for metric, threshold in gate_thresholds.items():
                if metric in computed and computed[metric] < threshold:
                    failures.append(f"{metric}={computed[metric]:.4f} < threshold={threshold}")

            if failures:
                raise ValueError(f"Model failed evaluation gates: {', '.join(failures)}")

            return json.dumps(computed)

        return evaluate_model

    def local_run(
        self,
        context: "MLContext",
        model_path: str = "",
        eval_dataset_path: str = "",
        **kwargs: Any,
    ) -> dict[str, float]:
        """Return synthetic metric values locally (no real model evaluation)."""
        import random

        computed = {m: round(random.uniform(0.75, 0.95), 4) for m in self.metrics}
        print(f"[local] EvaluateModel: metrics={computed}")

        failures = [
            f"{m}={v:.4f} < {self.gate[m]}"
            for m, v in computed.items()
            if m in self.gate and v < self.gate[m]
        ]
        if failures:
            raise ValueError(f"[local] Gate failures: {', '.join(failures)}")

        return computed
