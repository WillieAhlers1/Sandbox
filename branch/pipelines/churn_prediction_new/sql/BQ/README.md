# BigQuery SQL Files

These SQL files create BigQuery tables for the feature engineering pipeline.

## Naming Convention
- Pattern: `dsci-{project}-{component}-{branch}`
- Example: `dsci-churn-prediction-raw-main`

## Files
- `raw_events.sql`: Extract raw events data
- `features_engagement.sql`: User engagement metrics
- `features_behavior.sql`: User behavior patterns

## Best Practices
1. Use `CURRENT_TIMESTAMP()` for dynamic timestamps
2. Reference datasets with `{{{{project_id}}}}.{{{{bq_dataset}}}}`
3. Handle NULL values explicitly
4. Use SAFE_DIVIDE for division operations
5. Include data quality checks
