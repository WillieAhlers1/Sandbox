# House price serving image — extends base, adds FastAPI + uvicorn.
ARG BASE_IMAGE=base
FROM ${BASE_IMAGE}

# Serving dependencies
RUN /app/.venv/bin/pip install --no-cache-dir fastapi "uvicorn[standard]"

# Copy serving application code
COPY app/house_price/ /app/app/house_price/

# Vertex AI custom container requirements:
# - Listen on AIP_HTTP_PORT (default 8080)
# - Health endpoint at AIP_HEALTH_ROUTE (default /health)
# - Prediction endpoint at AIP_PREDICT_ROUTE (default /predict)
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "app.house_price.app:app", "--host", "0.0.0.0", "--port", "8080"]
