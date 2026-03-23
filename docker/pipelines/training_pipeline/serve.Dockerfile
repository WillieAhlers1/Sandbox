# Training pipeline serving image — extends base, adds FastAPI + uvicorn.
ARG BASE_IMAGE=base
FROM ${BASE_IMAGE}

# Serving dependencies
RUN /app/.venv/bin/pip install --no-cache-dir fastapi "uvicorn[standard]"

# Copy serving application code
COPY app/training_pipeline/ /app/app/training_pipeline/

# Vertex AI custom container requirements:
# - Listen on AIP_HTTP_PORT (default 8080)
# - Health endpoint at AIP_HEALTH_ROUTE (default /health)
# - Prediction endpoint at AIP_PREDICT_ROUTE (default /predict)
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "app.training_pipeline.app:app", "--host", "0.0.0.0", "--port", "8080"]
