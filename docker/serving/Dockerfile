# Slim serving image: only what's needed for model inference
ARG BASE_IMAGE=base-python:latest
FROM ${BASE_IMAGE}

WORKDIR /app

RUN python -m venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Serving-time deps only (no KFP, BQ, Airflow)
RUN uv pip install scikit-learn pandas numpy google-cloud-storage loguru

# Only what's needed for model unpickling + serving
COPY second_run/ /app/second_run/
COPY gcp_ml_framework/__init__.py /app/gcp_ml_framework/__init__.py
COPY gcp_ml_framework/serving/ /app/gcp_ml_framework/serving/

ENV PYTHONPATH="/app:${PYTHONPATH}"
EXPOSE 8080
CMD ["python", "-m", "gcp_ml_framework.serving.handler"]
