# Feature Store SQL Files

These SQL files define Feature Store entities for the pipeline.

## Naming Convention
- Pattern: `fs_{team}_{project}_{entity}_{branch}`
- Example: `fs_dsci_churn_prediction_user_main`

## Entity Files
- `entity_user.sql`: User entity definition
- `entity_session.sql`: Session entity definition

## Best Practices
1. Entity files must have `entity_id` column
2. Include timestamp columns
3. Use DISTINCT to prevent duplicates
4. Match schema in Feature Store feature exports
