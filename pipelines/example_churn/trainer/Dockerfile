FROM python:3.11-slim

RUN pip install --no-cache-dir \
    "scikit-learn>=1.5,<1.6" \
    google-cloud-bigquery>=3.17 \
    google-cloud-storage>=2.14 \
    pandas>=2 \
    db-dtypes>=1.2

COPY train.py /app/train.py

ENTRYPOINT ["python", "/app/train.py"]
