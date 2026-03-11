ARG BASE_IMAGE=base-python:latest
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir \
    google-cloud-bigquery>=3.17 \
    google-cloud-storage>=2.16 \
    google-cloud-aiplatform>=1.49 \
    pyarrow>=15 \
    pandas>=2 \
    db-dtypes>=1.2 \
    scikit-learn>=1.4 \
    kfp==2.15.2
