# Completed Phases

## Phase 1: Critical Runtime Bugs & Dead Code Removal — DONE (2026-03-23)

**Baseline:** 61 failed, 105 passed, 60 errors (228 total)
**Result:** 51 failed, 127 passed, 60 errors (+22 passing, -10 failing, 0 new regressions)

### Tasks Completed

| Task | What | Files Changed |
|------|------|---------------|
| 1.1 | Deleted `serving_image` NameError block | `compiler.py:305-307` — 4 lines deleted |
| 1.5 | Removed dead `"gcp_config"` from _INTERNAL_FIELDS | `base.py:28` — 1 word removed |
| 1.3 | Fixed `third_run` → `second_run` in 2 kept files | `base.Dockerfile:13`, `train_regression_model.py:15` |
| 1.4 | Added `gcs_prefix`/`namespace` as real BQQuery fields | `bq_query.py` — 2 fields added, `getattr` removed |
| 1.2 | Moved experiment tracking from dead code to `execute()` | `train.py` — code block moved from `run()` to `execute()` |
| 1.6 | Fixed `endpoint_name` → `model_name` in pipelines | `training_pipeline/pipeline.py:67`, `verification_pipeline/pipeline.py:74` |
| 1.7 | Specific exception catching in git helpers | `naming.py` — `except Exception:` → `except (SubprocessError, OSError, ValueError):` |

### Tests Written (15 new/fixed, all passing)

| Test | File | Verifies |
|------|------|----------|
| `test_internal_fields_set` | `test_base.py` | _INTERNAL_FIELDS exact membership |
| `test_internal_fields_all_exist_on_some_component` | `test_base.py` | No dead entries in _INTERNAL_FIELDS |
| `test_has_template_fields` | `test_bq_query.py` | gcs_prefix/namespace are real Pydantic fields |
| `test_template_fields_default_empty` | `test_bq_query.py` | Defaults to empty string |
| `test_execute_no_getattr_fallback` | `test_bq_query.py` | No getattr in execute() |
| `test_house_price_step_imports` | `test_imports.py` | house_price imports from second_run |
| `test_second_run_estimator_importable` | `test_imports.py` | second_run.estimator works |
| `test_all_pipeline_deploy_steps_use_model_name` | `test_pipeline_definitions.py` | All DeployModel steps have non-empty model_name |
| `test_no_endpoint_name_in_pipeline_source` | `test_pipeline_definitions.py` | No endpoint_name= in source |
| `test_get_git_branch_without_environment_var` | `test_naming.py` | No KeyError when ENVIRONMENT unset |
| `test_get_git_branch_non_local_returns_local` | `test_naming.py` | Non-local env returns "local" |
| `test_get_git_branch_catches_specific_exceptions` | `test_naming.py` | No bare except Exception |
| `test_get_git_sha_catches_specific_exceptions` | `test_naming.py` | No bare except Exception |
| `test_train_logs_experiment` (fixed) | `test_train.py` | Experiment tracking runs in execute() |
| `test_train_experiment_failure_non_fatal` | `test_train.py` | Tracking failure doesn't crash pipeline |

### Key Lessons
- Test subclass `run()` must return correct types matching `execute()` expectations
- `_INTERNAL_FIELDS` entries can exist on subclasses (RegisterModel, DeployModel), not just BaseComponent
- Pydantic BaseSettings defaults to `extra="forbid"`, NOT `extra="ignore"` — `endpoint_name=` caused hard crashes, not silent drops
- Phase fixes cascade: fixing pipeline defs unblocked 22 import-dependent tests

---

## Phase 2: Ruff Compliance (18 → 0) — DONE (2026-03-23)

**Baseline:** 51 failed, 127 passed, 60 errors | 18 ruff errors
**Result:** 51 failed, 127 passed, 60 errors | **0 ruff errors** (zero test regressions)

### Tasks Completed

| Task | What | Errors Fixed |
|------|------|-------------|
| 2.1 | Auto-fix import sorting + whitespace | I001 ×7 + W293 ×1 + UP035 ×1 + F401 ×2 = 11 |
| 2.2 | Clean dangling TYPE_CHECKING block | Manual cleanup after auto-fix |
| 2.3 | Break long lines | E501 ×4 (config.py ×2, naming.py, compiler.py) |
| 2.4 | (Done by 2.1) Callable → collections.abc | UP035 auto-fixed |
| 2.5 | Suppress UP047 with noqa | UP047 ×3 (overload + TypeVar pattern intentional) |

### Files Modified (8)
`__init__.py`, `base.py`, `register.py`, `config.py`, `decorators.py`, `naming.py`, `compiler.py`, `test_naming.py`, `test_base.py`

### Key Lessons
- `ruff check --fix` handles more than target rules — always inspect the diff
- Suppress UP047 deliberately when overload + TypeVar is the correct pattern
- Auto-fix can leave dangling blocks (empty `if TYPE_CHECKING: pass`) — clean manually

---

## Phase 3: Test Infrastructure Fix (conftest — 60 errors → 0) — DONE (2026-03-23)

**Baseline:** 51 failed, 127 passed, 60 errors | 0 ruff errors
**Result:** 60 failed, 178 passed, **0 errors** | 0 ruff errors (+51 passing, -60 errors, +9 failures from previously-masked tests)

### Tasks Completed

| Task | What | Files Changed |
|------|------|---------------|
| 3.1 | `dev_project_id=` → `project_id=` in conftest fixture | `tests/conftest.py:28` — 1 kwarg renamed |
| 3.2 | `"GML_ENVIRONMENT"` → `"ENVIRONMENT"` in conftest fixture | `tests/conftest.py:35` — 1 env var name fixed |

### Impact
- 60 errors → 0 errors (fixture no longer crashes at setup)
- 51 previously-erroring tests now PASS
- 9 previously-erroring tests now FAIL (they test old APIs — Phase 4 scope)
- 127 → 178 passing tests

### Key Lessons
- Fixture errors mask test outcomes — fixing one fixture can flip 60 results
- Pydantic `extra="ignore"` silently drops wrong field names, producing misleading error messages

---

## Phase 4: Test Fixes by Root Cause (60 → 0 failures) — DONE (2026-03-23)

**Baseline:** 60 failed, 178 passed, 0 errors | 0 ruff errors
**Result:** **0 failed, 232 passed, 0 errors** | 0 ruff errors (+54 passing, -60 failures)

### Tasks Completed

| Task | Root Cause | Failures Fixed | Key Change |
|------|-----------|----------------|------------|
| 4.1 | `._task_type` → `.task_type` | 12 | Find/replace in 6 test files + add `@ml_task` to DummyML helpers |
| 4.2 | Config multi-env project IDs | 9 | Rewrote for single `project_id`, removed `GML_*` env vars |
| 4.3 | Context `is_production` | 2 | Fixed `_make_context()` helper GCPConfig + env vars |
| 4.4 | DeployModel field renames | 9 | Full rewrite — `model_name=`, no serving image fields |
| 4.5 | Vertex utils old signature | 9 | Full rewrite — no `model_uri`, model lookup by display_name |
| 4.6 | TrainModel missing fields | 3 | Removed `trainer_args`/`_work_dir` assertions, fixed `run()` return types |
| 4.7 | RegisterModel CPR routes | 2 | Deleted `TestRegisterModelCPR` class |
| 4.8 | Compiler `serving_image=` param | 3 | Changed to `default_image=`, DeployModel test validates NO serving image |
| 4.9 | Smart compiler GCPConfig | 8 | Fixed `staging_project_id` → `project_id`, added `@ml_task` to DummyML |

### Files Modified (14 test files)
`test_decorators.py`, `test_bq_query.py`, `test_bq_transform.py`, `test_email.py`, `test_write_features.py`, `test_unified_builder.py`, `test_config.py`, `test_context.py`, `test_deploy.py`, `test_vertex.py`, `test_train.py`, `test_register.py`, `test_compiler.py`, `test_smart_compiler.py`

### Key Lessons
- Update TESTS to match new API, never revert source to match old tests
- BaseComponent defaults to TASK — DummyML helpers need explicit `@ml_task`
- Parallelize independent test rewrites with background agents

---

## Phase 5: Config, Scaffolding & Defaults — DONE (2026-03-23)

**Baseline:** 0 failed, 232 passed, 0 errors | 0 ruff errors
**Result:** 0 failed, **235 passed**, 0 errors | 0 ruff errors (+3 new template tests)

### Tasks Completed

| Task | What | Files Changed |
|------|------|---------------|
| 5.3 | `cache_enabled: bool = False` | `base.py:58` — 1 default changed |
| 5.4 | `enable_caching: bool = False` in runner | `runner.py:29` — 1 default changed |
| 5.1 | All cmd_init templates + function sig | `cmd_init.py` — `.env`, pipeline, 4 CI workflows, `init_project()` |
| 5.2 | Clean `.env.example` | `.env.example` — removed derived vars, GML_ prefix |

### Tests Written (3 new)
- `test_dot_env_template_uses_correct_var_names` — no GML_ prefix in .env template
- `test_pipeline_template_uses_model_name` — model_name not endpoint_name
- `test_ci_templates_use_correct_var_names` — no GML_ prefix in CI workflows

### Key Lessons
- Keep old CLI flag as alias when renaming parameters (`--dev-project` → `--gcp-project`)
- Template strings with f-string braces need careful counting for YAML workflows

### Cumulative Progress (Phases 1-5)
| Metric | Start | Phase 4 | Phase 5 |
|--------|-------|---------|---------|
| Passed | 105 | 232 | **235** |
| Failed | 61 | 0 | **0** |
| Errors | 60 | 0 | **0** |
| Ruff | 18 | 0 | **0** |

---

## Phase 6: Pydantic Migration & Code Cleanup — DONE (2026-03-23)

**Baseline:** 0 failed, 235 passed, 0 errors | 0 ruff errors
**Result:** 0 failed, **237 passed**, 0 errors | 0 ruff errors (+2 new tests)

### Tasks Completed

| Task | What | Files Changed |
|------|------|---------------|
| 6.1 | `@dataclass` → Pydantic `BaseModel` | `smart_compiler.py` — 2 classes converted, `PipelineStep` moved to runtime import |
| 6.2 | Verify experiment tracking | Already done in Phase 1.2 — verified green |
| 6.3 | Add `__main__` to email.py | `email.py` — 3 lines added |
| 6.4 | `import logging` → loguru | `cmd_deploy.py` — 2 lines changed |
| 6.5 | Fix context.py field order | `context.py` — moved `pipeline_service_account_email` before `@property` |
| 6.6 | Fix WriteFeatures `render_operator()` | `write_features.py` — generates function definition + operator |
| 6.7 | Regenerate DAGs | 3 stale DAGs deleted, 3 recompiled, all valid Python |

### Key Lessons
- `TYPE_CHECKING` imports break Pydantic `BaseModel` fields at runtime — must be runtime imports
- Always run `ruff check --fix` immediately after manual import changes

---

## Phase 7: Docker Cleanup, Cloud Build & Build Script — DONE (2026-03-23)

**Baseline:** 0 failed, 237 passed, 0 errors | 0 ruff errors | 8 Dockerfiles
**Result:** 0 failed, **237 passed**, 0 errors | 0 ruff errors | **3 Dockerfiles** (5 legacy deleted)

### Tasks Completed

| Task | What | Files Changed |
|------|------|---------------|
| 7.4 | Re-added `sync=False` to RegisterModel | `register.py` — 1 line added to `upload_kwargs` |
| 7.5 | Verified `{branch}-{sha}` tag format | No change — already correct |
| 7.1 | Deleted 5 legacy Dockerfiles | `docker/train.Dockerfile`, `docker/serve.Dockerfile`, `docker/pipeline/`, `docker/serving/`, `docker/pipelines/house_price/train.Dockerfile` |
| 7.2 | Rewrote `cloudbuild.yaml` | Per-pipeline paths + `--base`/`--serve` naming convention |
| 7.3 | Cleaned `docker_build.sh` | Removed `_build_root_defaults`, `_build_serving`, legacy refs |

### Docker Hierarchy (Final)
```
docker/base/base-python/Dockerfile           — Tier 0: foundation
docker/pipelines/house_price/base.Dockerfile — Tier 1: per-pipeline execution
docker/pipelines/house_price/serve.Dockerfile — Tier 1: per-pipeline serving
```

### Key Lessons
- Check for ALL callers before deleting a function — grep the entire codebase
- cloudbuild.yaml serve image BASE_IMAGE should point to pipeline base, not base-python

### Cumulative Progress (Phases 1-7)
| Metric | Start | Phase 6 | Phase 7 |
|--------|-------|---------|---------|
| Passed | 105 | 237 | **237** |
| Failed | 61 | 0 | **0** |
| Errors | 60 | 0 | **0** |
| Ruff | 18 | 0 | **0** |
| Dockerfiles | 8 | 8 | **3** |
| @dataclass | 2 | 0 | **0** |

---

## Phase 8: New Capabilities — DONE (2026-03-23)

**Baseline:** 0 failed, 237 passed, 0 errors | 0 ruff errors | 18 mypy errors
**Result:** 0 failed, **244 passed**, 0 errors | **0 ruff errors** | **0 mypy errors** (+7 new tests)

### Tasks Completed

| Task | REQS | What | Files Changed |
|------|------|------|---------------|
| 8.1 | 9.0 | Removed stale loguru comment | `feature_store/client.py` — 1 comment |
| 8.3 | 17.0 | Fixed 18 mypy errors → 0 | 7 framework files + `pyproject.toml` (added `types-PyYAML`, `disable_error_code`) |
| 8.7 | — | GCP best practices | 8 exception fixes, `gcp_conn_id` configurable on BQQuery + BQTransform |
| 8.4 | 19.0 | New `DBTRun` component | `dbt_run.py` (new) + `__init__.py` export + 7 tests |
| 8.2 | 22.0 | Loop/condition design doc | `docs/design_loop_condition.md` (implementation deferred) |
| 8.5 | 10.0+20.0 | Documentation | `AGENTS.md` created |
| 8.6 | 18.0 | Cloud Build IAM documented | `docs/cloud_build_iam.md` created |

### Tests Written (7 new — DBTRun)
- `test_is_task_type` — TaskType.TASK
- `test_instantiation` — default fields
- `test_renders_bash_operator` — BashOperator + `dbt run`
- `test_includes_models_flag` — `--models` in output
- `test_includes_vars_flag` — `--vars` in output
- `test_includes_target` — `--target` in output
- `test_has_main_block` — `__main__` guard

### Key Lessons
- mypy `import-untyped` is different from `import` — needs `disable_error_code`
- Always use `# type: ignore[specific-code]`, never bare `# type: ignore`
- Parallelize large phases with 3 background agents on independent file sets

### Final Cumulative Progress (ALL PHASES)
| Metric | Start (Pre-Phase 1) | End (Post-Phase 8) | Change |
|--------|---------------------|---------------------|--------|
| Passed | 105 | **244** | **+139** |
| Failed | 61 | **0** | **-61** |
| Errors | 60 | **0** | **-60** |
| Ruff errors | 18 | **0** | **-18** |
| Mypy errors | 18 | **0** | **-18** |
| @dataclass | 2 | **0** | **-2** |
| Dockerfiles | 8 | **3** | **-5** |
| New components | 0 | **1** (DBTRun) | **+1** |
| New docs | 0 | **3** (AGENTS.md, loop/condition, Cloud Build IAM) | **+3** |

### REQS Final Status
| Status | Count | REQS |
|--------|-------|------|
| **DONE** | 15 | 1.0, 2.0, 4.0, 5.0, 6.0, 8.0, 9.0, 11.0, 12.0, 13.0, 14.0, 15.0, 17.0, 18.0b, 21.0 |
| **PARTIAL** | 4 | 3.0 (DAGs regenerated), 10.0 (docstrings partial), 18.0 (Cloud Build documented), 19.0 (DBTRun exists, needs Composer verification) |
| **DESIGN ONLY** | 1 | 22.0 (loop/condition — design doc, implementation deferred) |
| **NOT DONE** | 1 | 20.0 (AGENTS.md created but could be more comprehensive) |
| **DEFERRED** | 1 | 16.0 (CI/CD separation) |

### Cumulative Progress (Phases 1-6)
| Metric | Start | Phase 5 | Phase 6 |
|--------|-------|---------|---------|
| Passed | 105 | 235 | **237** |
| Failed | 61 | 0 | **0** |
| Errors | 60 | 0 | **0** |
| Ruff | 18 | 0 | **0** |
| @dataclass | 2 | 2 | **0** |

### Cumulative Progress (Phases 1-4)
| Metric | Start | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|--------|-------|---------|---------|---------|---------|
| Passed | 105 | 127 | 127 | 178 | **232** |
| Failed | 61 | 51 | 51 | 60 | **0** |
| Errors | 60 | 60 | 60 | 0 | **0** |
| Ruff | 18 | 17 | 0 | 0 | **0** |
