# House price training image.
# Inherits from the root-level default training image.
# Just use the stem name — the build script resolves it automatically.
ARG BASE_IMAGE=train
FROM ${BASE_IMAGE}

# Add pipeline-specific training deps here (uncomment as needed):
# RUN pip install xgboost lightgbm
