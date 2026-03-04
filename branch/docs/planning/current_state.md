# Current State

> Last updated: 2026-03-03 | Branch: `feature_dagFactory`

## What Works

The core ML loop runs end-to-end on Vertex AI:

```
bigquery-extract → bq-transform → write-features → train-model → evaluate-model → deploy-model
```

### Completed modules

| Module | Status |
|---|---|
| `naming.py` — all GCP resource names from `{team}-{project}-{branch}` | Complete |
| `config.py` — Pydantic v2 layered config | Complete |
| `context.py` — MLContext single runtime object | Complete |
| `secrets/client.py` — `!secret` refs, local env fallback | Complete |
| `pipeline/builder.py` — PipelineBuilder fluent DSL | Complete |
| `pipeline/compiler.py` — PipelineDefinition → KFP v2 YAML | Complete |
| `pipeline/runner.py` — LocalRunner (DuckDB) + VertexRunner | Complete |
| 7 built-in components (BigQueryExtract, BQTransform, WriteFeatures, ReadFeatures, TrainModel, EvaluateModel, DeployModel) | Complete |
| `dag/factory.py` — single-Vertex-pipeline DAG generation | Complete (limited) |
| `dag/operators.py` — VertexPipelineOperator | Complete |
| Feature Store schema parser | Complete |
| Feature Store client (legacy API) | Partial |
| 99 unit tests, ruff clean | Passing |

### CLI commands

| Command | Status |
|---|---|
| `gml init project` / `gml init pipeline` | Complete |
| `gml run --local` / `--vertex` / `--compile-only` | Complete |
| `gml context show` | Complete |
| `gml deploy dags` | Partial |
| `gml deploy features` | Partial |
| `gml promote` | Partial |
| `gml teardown` | Not started |
| `gml lint` | Not started |

## What Doesn't Work

- **DAG factory** only supports one Vertex pipeline per DAG — no arbitrary task composition
- **PipelineBuilder** is ML-only — no pure data engineering workflows
- **Steps are strictly sequential** — no parallel branches or conditional logic
- **Feature Store uses legacy API** — slow (~10 min for 10 rows)
- **Composer env naming** implies one per branch (should be shared per project)
- **DAG GCS path** is constructed, not discovered from Composer API
- **No integration tests** — directory exists but is empty
- **No CI/CD workflows** — `.github/workflows/` not implemented

## Known Pain Points

- Silent 0-row failures (pipeline continues with empty data)
- Local run metrics don't match Vertex (random vs real sklearn)
- No pipeline progress visibility beyond `current state: 3`
- No single-step re-run on failure
- Schedule defined in PipelineBuilder but unused without Composer
- No `gml status` or `gml logs` commands

## Codebase Stats

| Metric | Count |
|---|---|
| Framework library | ~2,356 lines |
| Unit tests | ~1,400 lines |
| Test count | 99 passing |
| Example pipeline | 113 lines |
