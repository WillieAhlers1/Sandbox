SELECT
    user_id,
    item_id,
    interaction_type,
    ts
FROM `{bq_dataset}.raw_interactions`
WHERE ts >= '{run_date}'
