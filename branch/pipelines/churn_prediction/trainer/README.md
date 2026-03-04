# Trainer Container

This folder contains the training code and Docker configuration for the churn_prediction pipeline.

## Files
- `Dockerfile`: Container configuration
- `train.py`: Training script
- `requirements.txt`: Python dependencies

## Building the Image
```bash
docker build -t churn_prediction-trainer:latest .
```

## Running Locally
```bash
docker run --rm \
  -e GCP_PROJECT_ID=prj-xxx \
  -e BQ_DATASET_ID=dsci_churn_prediction_main \
  churn_prediction-trainer:latest
```

## Environment Variables
- `GCP_PROJECT_ID`: GCP project ID
- `BQ_DATASET_ID`: BigQuery dataset
- `BQ_TABLE_ID`: Training data table
- `MODEL_OUTPUT_PATH`: Where to save the trained model
