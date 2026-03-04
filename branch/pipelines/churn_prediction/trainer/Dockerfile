FROM python:3.11-slim

WORKDIR /app

# Install ML dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY trainer/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy trainer code
COPY trainer/train.py .

# Run trainer
ENTRYPOINT ["python", "train.py"]
