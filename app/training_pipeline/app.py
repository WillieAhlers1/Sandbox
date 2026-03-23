"""Serving application for the training_pipeline regression model.

Vertex AI custom container requirements:
- Listen on AIP_HTTP_PORT (default 8080)
- Health endpoint at AIP_HEALTH_ROUTE (default /health)
- Prediction endpoint at AIP_PREDICT_ROUTE (default /predict)
"""

import os
import pickle

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Training Pipeline — House Price Model")

# Model is loaded once at startup from the artifact directory
_model = None
MODEL_PATH = os.environ.get("AIP_STORAGE_URI", "/app/model")


class PredictRequest(BaseModel):
    instances: list


class PredictResponse(BaseModel):
    predictions: list


def _download_from_gcs(gcs_uri: str, local_path: str) -> None:
    """Download a file from GCS to a local path."""
    from google.cloud import storage

    # Parse gs://bucket/blob/path
    without_scheme = gcs_uri.replace("gs://", "")
    bucket_name, _, blob_path = without_scheme.partition("/")
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.download_to_filename(local_path)


def _load_model():
    global _model
    if _model is None:
        if MODEL_PATH.startswith("gs://"):
            # Vertex AI custom containers get a GCS URI — download locally
            local_dir = "/tmp/model"  # noqa: S108
            os.makedirs(local_dir, exist_ok=True)
            local_file = os.path.join(local_dir, "model.pkl")
            gcs_file = MODEL_PATH.rstrip("/") + "/model.pkl"
            _download_from_gcs(gcs_file, local_file)
        else:
            local_file = os.path.join(MODEL_PATH, "model.pkl")
        with open(local_file, "rb") as f:
            _model = pickle.load(f)  # noqa: S301
    return _model


@app.on_event("startup")
def startup():
    _load_model()


@app.get(os.environ.get("AIP_HEALTH_ROUTE", "/health"))
def health():
    if _model is None:
        return JSONResponse({"status": "not ready"}, status_code=503)
    return {"status": "healthy"}


@app.post(os.environ.get("AIP_PREDICT_ROUTE", "/predict"))
def predict(request: PredictRequest) -> PredictResponse:
    import pandas as pd

    model = _load_model()
    df = pd.DataFrame(request.instances)
    predictions = model.predict(df)
    return PredictResponse(predictions=predictions.tolist())
