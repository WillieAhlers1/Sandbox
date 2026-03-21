# Phase 4: Training Pipeline E2E on GCP

## Goal
Prove the unified architecture works end-to-end: seed data → local run → compile → build → deploy → trigger via Composer.

## Critical Bug Fix (Before Any GCP Steps)

**Problem:** `training_pipeline_features.sql` hardcodes `demo_housing_data.housing_data_table`, but `seed_bq.sh` seeds into the context-derived dataset (`mlplatform_second_run_version_`). SQL and data live in different datasets → query fails.

**Fix (3 files, ~5 lines):**
1. Add `dataset: str = ""` to `BaseComponent` universal params (like `project`, `region`, `branch`)
2. Change SQL to `SELECT * FROM {dataset}.housing_data_table`
3. Update `HouseTrainModelStep.run()` to format SQL with `self.dataset`

**Why `dataset` on BaseComponent:**
- `_build_context_params` already passes `"dataset": context.bq_dataset` — but no component declares the field, so it's filtered out (dead code)
- Adding it follows the established pattern: `project`, `region`, `branch`, `environment` are all context-derived universal params
- Enables branch isolation for BQ data (the whole point of NamingConvention)

---

## Implementation Order

```
Task 1: Tests first (TDD)                    — tests/training_pipeline/
Task 2: Fix dataset field + SQL              — base.py, SQL, train step
Task 3: Verify unit tests pass               — pytest
Task 4: Seed BigQuery data                   — seed_bq.sh
Task 5: Run gml run --local                  — verify local execution
Task 6: Compile pipeline                     — gml compile
Task 7: Build Docker image                   — gml build (Cloud Build)
Task 8: Deploy to GCP                        — gml deploy
Task 9: Remove --vertex, add Composer trigger — cmd_run.py refactor
Task 10: Trigger DAG via Composer             — gml run training_pipeline
```

---

## Task 1: Tests (TDD)

**Create:** `tests/training_pipeline/__init__.py`, `tests/training_pipeline/test_steps.py`, `tests/training_pipeline/test_e2e.py`

Tests in `test_steps.py` (unit):
- `test_train_step_instantiation` — HouseTrainModelStep can be instantiated
- `test_train_step_has_dataset_field` — dataset field exists and is populated by context params
- `test_train_step_sql_uses_dataset_template` — SQL contains `{dataset}` placeholder, not hardcoded dataset
- `test_step_cli_help` — `HouseTrainModelStep` responds to --help (via subprocess)

Tests in `test_e2e.py` (e2e markers, won't run in unit suite):
- `test_compile_produces_yaml` — gml compile produces valid YAML with correct image URI
- `test_local_run_completes` — gml run --local completes without error (requires GCP auth + seeded data)

---

## Task 2: Fix Dataset Field + SQL

**File 1:** `gcp_ml_framework/components/base.py` line 71
```python
# Add after run_date: str = ""
dataset: str = ""
```

**File 2:** `pipelines/training_pipeline/sql/training_pipeline_features.sql`
```sql
SELECT *
FROM {dataset}.housing_data_table
```

**File 3:** `pipelines/training_pipeline/steps/train_house_model.py` line 37
```python
# Before: query = files(...).read_text()
# After:
query_template = files(...).read_text()
query = query_template.format(dataset=self.dataset)
```

---

## Tasks 4-8: GCP Verification

These are command executions, not code changes. Each verifies a link in the E2E chain:

| Task | Command | Verification |
|------|---------|-------------|
| 4 | `./scripts/seed_bq.sh` | BQ dataset created, table has 50 rows |
| 5 | `gml run training_pipeline --local` | Pipeline completes, model.pkl in GCS |
| 6 | `gml compile training_pipeline` | YAML + DAG produced, correct image URIs |
| 7 | `gml build training_pipeline` | Image in AR with correct tag |
| 8 | `gml deploy training_pipeline` | DAG uploaded to Composer, YAML to GCS |

---

## Task 9: Remove --vertex, Replace with Composer Trigger

**Why:** The `--vertex` flag bypasses Composer and submits directly to Vertex AI. This contradicts the architecture where Composer is the sole orchestrator. Mixed pipelines with `@task` steps would silently skip those steps. The architecture (discussion.md) never mentions `--vertex` — data scientists use `--local` for dev and `gml deploy` + Composer for GCP execution.

**What changes:**
- Remove `--vertex` flag and `_run_vertex()` from `cmd_run.py`
- Remove `--sync` and `--no-cache` flags (Composer handles these)
- `gml run pipeline` (default, no flag) → triggers the deployed DAG in Composer via `gcloud composer environments run`
- `gml run pipeline --local` → stays as-is (in-process execution)
- `VertexRunner` class stays as internal utility (DAG's `RunPipelineJobOperator` uses the same logic conceptually)
- Update tests in `tests/cli/test_commands.py`

**Files:**
| File | Action |
|------|--------|
| `gcp_ml_framework/cli/cmd_run.py` | MODIFY — remove `--vertex`, add Composer trigger |
| `tests/cli/test_commands.py` | MODIFY — update run command tests |

---

## Task 10: Trigger DAG via Composer

After Task 9, verify E2E:
```bash
UV_ENV_FILE=.env uv run -- gml run training_pipeline
```

This should trigger the deployed DAG in Composer → Composer's `RunPipelineJobOperator` submits to Vertex AI → pipeline completes.

---

## File Change Summary

| File | Action | Lines |
|------|--------|-------|
| `gcp_ml_framework/components/base.py` | MODIFY | +1 (add `dataset` field) |
| `pipelines/training_pipeline/sql/training_pipeline_features.sql` | MODIFY | 1 line |
| `pipelines/training_pipeline/steps/train_house_model.py` | MODIFY | +2 lines |
| `tests/training_pipeline/__init__.py` | CREATE | 0 |
| `tests/training_pipeline/test_steps.py` | CREATE | ~40 |
| `tests/training_pipeline/test_e2e.py` | CREATE | ~30 |
| `gcp_ml_framework/cli/cmd_run.py` | MODIFY | refactor ~80 lines |
| `tests/cli/test_commands.py` | MODIFY | update run tests |

## Edge Cases
- SQL `.format()` is safe here — the SQL has no other curly braces
- `dataset` field defaults to `""` — won't break existing components that don't use it
- `seed_bq.sh` is idempotent (`--replace` flag on bq load)
- Cloud Build may fail on first run if AR repo doesn't exist → `bootstrap.sh` creates it
- Composer trigger requires DAG to be deployed first (`gml deploy`) — `gml run` without deploy should error clearly
