FROM python:3.11-slim

RUN pip install --no-cache-dir google-cloud-storage

COPY train.py /app/train.py

ENTRYPOINT ["python", "/app/train.py"]
