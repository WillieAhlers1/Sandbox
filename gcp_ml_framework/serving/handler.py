"""Generic prediction HTTP server for Vertex AI Custom Prediction Routines.

Vertex AI protocol:
  - AIP_STORAGE_URI  env var → GCS path to model artifacts
  - AIP_HTTP_PORT    env var → port (default 8080)
  - POST /predict    with {"instances": [...]} → {"predictions": [...]}
  - GET  /health     → 200

On startup the server downloads model.pkl from GCS and unpickles it.
Works with any model that exposes a ``predict(pd.DataFrame)`` method.
"""

from __future__ import annotations

import json
import os
import pickle
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from loguru import logger


def _load_model():
    """Download model.pkl from AIP_STORAGE_URI and unpickle it."""
    from google.cloud import storage

    storage_uri = os.environ.get("AIP_STORAGE_URI", "")
    if not storage_uri:
        raise RuntimeError("AIP_STORAGE_URI is not set")

    # Parse gs://bucket/path/to/dir → bucket, blob prefix
    uri = storage_uri.removeprefix("gs://")
    bucket_name, *prefix_parts = uri.split("/")
    blob_prefix = "/".join(prefix_parts).rstrip("/")
    blob_path = f"{blob_prefix}/model.pkl" if blob_prefix else "model.pkl"

    logger.info("Downloading model from gs://{}/{}", bucket_name, blob_path)

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
        blob.download_to_filename(tmp.name)
        with open(tmp.name, "rb") as f:
            model = pickle.load(f)  # noqa: S301

    logger.info("Model loaded: {}", type(model).__name__)
    return model


# Module-level model singleton, loaded once at import / startup
_model = None


class PredictionHandler(BaseHTTPRequestHandler):
    """HTTP handler implementing Vertex AI prediction protocol."""

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._respond(200, {"status": "healthy"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/predict":
            self._respond(404, {"error": "not found"})
            return

        try:
            import pandas as pd

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body)

            instances = payload.get("instances")
            if instances is None:
                self._respond(400, {"error": "missing 'instances' key"})
                return

            df = pd.DataFrame(instances)
            result = _model.predict(df)

            # Convert predictions to list of dicts or list of values
            if hasattr(result, "to_dict"):
                predictions = result.to_dict(orient="records")
            else:
                predictions = list(result)

            self._respond(200, {"predictions": predictions})
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            self._respond(400, {"error": str(exc)})
        except Exception as exc:
            logger.exception("Prediction failed")
            self._respond(500, {"error": str(exc)})

    def _respond(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):  # noqa: A002
        """Route access logs through loguru instead of stderr."""
        logger.info(format, *args)


def serve() -> None:
    """Start the prediction server."""
    global _model  # noqa: PLW0603
    _model = _load_model()

    port = int(os.environ.get("AIP_HTTP_PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), PredictionHandler)  # noqa: S104
    logger.info("Serving on port {}", port)
    server.serve_forever()


if __name__ == "__main__":
    serve()
