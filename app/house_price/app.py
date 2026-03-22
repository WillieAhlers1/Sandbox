"""Serving application for the house_price regression model.

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

app = FastAPI(title="House Price Regression Model")

# Model is loaded once at startup from the artifact directory
_model = None
MODEL_PATH = os.environ.get("AIP_STORAGE_URI", "/app/model")


class PredictRequest(BaseModel):
    instances: list


class PredictResponse(BaseModel):
    predictions: list


def _load_model():
    global _model
    if _model is None:
        model_file = os.path.join(MODEL_PATH, "model.pkl")
        with open(model_file, "rb") as f:
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
