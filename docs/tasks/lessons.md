# Lessons Learned

## 2026-03-23: PR analysis must be thorough — read diffs AND docs, not just commit messages
- **Pattern**: Dismissed PR #26 as "documentation cleanup and minor fix" when it actually codified 10 non-negotiable design decisions (serving image ownership, model_name contract, Docker hierarchy).
- **Rule**: For every client PR, read the actual `git diff`, the updated docs, and understand WHY each change was made. The commit message is never sufficient.
- **Why**: Shallow analysis led to wrong REQS status (18.0b marked DONE when PARTIAL), missed bugs (sync=False discrepancy, legacy Dockerfiles), and wrong todo items. Days of rework.

## 2026-03-23: _INTERNAL_FIELDS entries may exist on subclasses, not just BaseComponent
- **Pattern**: Wrote a validation test checking every `_INTERNAL_FIELDS` entry against `BaseComponent.model_fields`. Test failed for `model_name` and `serving_dockerfile` — which are fields on `RegisterModel`/`DeployModel`, not `BaseComponent`.
- **Rule**: `_INTERNAL_FIELDS` applies at the BaseComponent level but filters fields from ANY subclass during `cli()` and `as_kfp_component()`. Validation must check against ALL component classes, not just the base.
- **Why**: _INTERNAL_FIELDS is a framework-wide exclusion set. A field being internal on RegisterModel (where it exists) is valid even though BaseComponent doesn't declare it.

## 2026-03-23: Test subclass run() must return the correct type
- **Pattern**: Experiment tracking test had `_TestTrainer.run()` returning `None`, but `TrainModel.execute()` calls `os.walk(artifact_location)` which fails with `TypeError: expected str, bytes or os.PathLike object, not NoneType`.
- **Rule**: When writing test subclasses that override `run()`, match the return type contract. If `execute()` uses the return value, the test must return a valid value (e.g., a `Path` to a temp directory with files).
- **Why**: `execute()` is the integration point — it calls `run()` then uses the result. A test that returns `None` tests nothing about the post-`run()` lifecycle (GCS upload, experiment tracking).

## 2026-03-23: Pydantic BaseSettings extra handling depends on configuration
- **Pattern**: Assumed `extra="ignore"` was the Pydantic default for BaseSettings, but `pydantic-settings` actually defaults to `extra="forbid"`. Pipeline definitions with `endpoint_name=` raised `ValidationError: Extra inputs are not permitted` instead of silently dropping.
- **Rule**: Check the actual `model_config` on the class. Don't assume Pydantic defaults — BaseModel and BaseSettings have DIFFERENT defaults, and subclasses can override.
- **Why**: This changed the severity assessment of Bug 6 (endpoint_name). It wasn't "silently dropped" — it was a hard crash at import time. More critical than initially assessed.

## 2026-03-23: Phase 1 fixes can reduce pre-existing test failures
- **Pattern**: Expected Phase 1 to maintain baseline (61 failed, 105 passed, 60 errors). Actual result: 51 failed, 127 passed (+22 passing, -10 failing). Several tests were failing because pipeline imports crashed on `endpoint_name=`.
- **Rule**: Track test counts before AND after each phase. Fixes often have cascading positive effects beyond the specific bug being fixed.
- **Why**: Fixing pipeline definitions (Task 1.6) unblocked import-dependent tests across training_pipeline and verification_pipeline test suites.

## 2026-03-23: Use `getattr` sparingly — prefer explicit fields
- **Pattern**: `bq_query.py` used `getattr(self, "gcs_prefix", "")` to silently default missing fields to empty string. This masked the fact that the field didn't exist and SQL templates got empty values.
- **Rule**: If a component needs a value, declare it as a Pydantic field. Never use `getattr` with a silent default to paper over missing fields. The compiler/local_runner will inject the value.
- **Why**: `getattr` hides bugs. An explicit field makes the dependency visible, type-checkable, and injectable by the framework.

## 2026-03-23: `ruff check --fix` handles more than just the target rules
- **Pattern**: Expected `ruff check --fix` to only fix I001 (import sorting) and W293 (whitespace). It also auto-fixed UP035 (moved `Callable` from `typing` to `collections.abc`) and cleaned up the F401 imports, leaving a dangling `if TYPE_CHECKING: pass` block.
- **Rule**: After auto-fix, always inspect the diff. Auto-fix can make broader changes than expected, and may leave behind empty blocks that need manual cleanup.
- **Why**: The dangling `TYPE_CHECKING` block was valid Python but useless code. Clean it up immediately rather than discovering it later.

## 2026-03-23: Suppress UP047 deliberately — overload + TypeVar is the correct pattern
- **Pattern**: Ruff UP047 wanted Python 3.12 PEP 695 type parameters (`def task[C](cls: C) -> C`) instead of TypeVar. But the `@overload` + `TypeVar` pattern across 3 `ml_task` signatures is the established idiom.
- **Rule**: When ruff suggests a syntax modernization that would break a well-established pattern (especially with `@overload`), suppress with `# noqa` and document why. Not every ruff suggestion is an improvement.
- **Why**: PEP 695 with `@overload` is newer and each function gets its own type parameter scope, making the shared `_C` across overloads behave differently. The TypeVar approach is correct, well-tested, and widely understood.

## 2026-03-23: Fixture errors mask test outcomes — fixing one fixture can flip 60 results
- **Pattern**: 60 tests showed as "errors" (not failures) because the conftest fixture crashed at setup. Fixing 2 lines in conftest converted them: 51 became passes, 9 became failures.
- **Rule**: When a shared fixture is broken, the error count is NOT the failure count. Errors mean "test didn't run." Once the fixture is fixed, previously-masked tests reveal their true state — some pass, some fail for different reasons.
- **Why**: Phase 3 changed the metric from "51 failed, 127 passed, 60 errors" to "60 failed, 178 passed, 0 errors." The 9 new failures aren't regressions — they're tests that now RUN and expose Phase 4 issues (old field names, old API signatures). Understanding this prevents panic when failure count temporarily increases.

## 2026-03-23: Pydantic `extra="ignore"` silently masks wrong field names
- **Pattern**: `GCPConfig(dev_project_id="test")` with `extra="ignore"` silently dropped `dev_project_id` without any warning. The required `project_id` field was left unset, causing `ValidationError: project_id Field required` — an error message that doesn't mention the actual mistake.
- **Rule**: When debugging Pydantic ValidationError on a required field, check if the caller passed the WRONG field name. `extra="ignore"` hides the real problem by silently dropping unknown kwargs.
- **Why**: The error says "project_id missing" but the real bug is "dev_project_id was passed instead." This misdirects debugging toward "why isn't project_id being set?" rather than "why is dev_project_id being used?"

## 2026-03-23: Update TESTS to match new API, never revert source to match old tests
- **Pattern**: Explore agent suggested adding removed fields back to source code (`endpoint_name` to DeployModel, `model_uri` to `run_deploy()`) to make old tests pass. This would undo the client's PR #25 design.
- **Rule**: When tests fail because the API changed intentionally (via client PRs), the tests are wrong — not the source. Always rewrite tests to validate the NEW API.
- **Why**: The source code implements the client's design decisions. Reverting it to pass stale tests defeats the purpose of the redesign. Tests exist to validate the current system, not to preserve the old one.

## 2026-03-23: BaseComponent defaults task_type to TASK — DummyML test helpers need @ml_task
- **Pattern**: Test helper `DummyML(BaseComponent)` without `@ml_task` decorator defaulted to `task_type=TASK`, causing mixed pipeline tests to see all steps as TASK and grouping to produce 1 group instead of 4.
- **Rule**: When creating test helper components that should be ML_TASK, always apply `@ml_task` decorator explicitly. BaseComponent defaults to `TaskType.TASK` (line 50 of base.py). There is no implicit ML_TASK inheritance.
- **Why**: The old code had `BaseComponent._task_type = ML_TASK` as default. The client's PR #23 changed decorators to set `task_type` as a ClassVar. Without the decorator, components are TASK by default — which is correct for @task components but wrong for ML test helpers.

## 2026-03-23: Parallelize independent test rewrites with background agents
- **Pattern**: Phase 4 had 60 test failures across 14 files with 10 root causes. Launching 2 background agents (config/context + deploy/vertex) while fixing other tests directly cut the wall-clock time significantly.
- **Rule**: When fixing multiple independent test files, identify which share no dependencies and launch background agents for those. Keep direct control of files that interact with each other.
- **Why**: Config tests and deploy tests don't share fixtures beyond conftest (already fixed). Running them in parallel is safe and saves time. The key constraint is not editing the same file from two places.

## 2026-03-23: Keep `--dev-project` as CLI alias when renaming parameters
- **Pattern**: Renamed `init_project(dev_project=)` to `init_project(gcp_project=)` but kept `--dev-project` as a CLI alias alongside `--gcp-project` for backward compatibility.
- **Rule**: When renaming a CLI parameter, add the new name as the primary flag but keep the old name as an alias. Use `typer.Option(..., "--new-name", "--old-name")` to support both.
- **Why**: Users who have scripts or muscle memory using `--dev-project` won't break. The old flag silently maps to the new parameter. Zero migration friction.

## 2026-03-23: Template strings with f-string braces need careful counting for YAML workflows
- **Pattern**: CI workflow templates use `${{{{ vars.X }}}}` (quadruple braces) because they're inside Python string literals that get `.format()` called. Each pair of `{{` produces one literal `{` in the output.
- **Rule**: When editing template strings that contain both Python `.format()` placeholders AND GitHub Actions `${{ }}` expressions, count braces: `${{{{ x }}}}` in Python source → `${{ x }}` in generated YAML. Don't add or remove braces during edits.
- **Why**: Getting the brace count wrong produces either `KeyError` (Python tries to format a GitHub Actions var) or invalid YAML (`${ vars.X }` instead of `${{ vars.X }}`).

## 2026-03-23: TYPE_CHECKING imports break Pydantic BaseModel fields at runtime
- **Pattern**: Converted `@dataclass` to Pydantic `BaseModel` in `smart_compiler.py`. `_StepGroup` had `steps: list[PipelineStep]` but `PipelineStep` was under `TYPE_CHECKING` (only available during static analysis). Pydantic raised `PydanticUserError: _StepGroup is not fully defined; you should define PipelineStep`.
- **Rule**: When a Pydantic model has a field typed with another class, that class MUST be importable at runtime — not just in `TYPE_CHECKING`. Move the import outside the guard, or call `model_rebuild()` after the import becomes available.
- **Why**: `@dataclass` tolerates forward references with `from __future__ import annotations` because it never resolves them at runtime. Pydantic `BaseModel` MUST resolve field types to build validators. `TYPE_CHECKING` imports are `None` at runtime — Pydantic can't build from `None`.

## 2026-03-23: Check for ALL callers of deleted functions — grep the entire codebase
- **Pattern**: Deleted `_build_serving()` from `docker_build.sh` but missed a call to it in the main loop at line 241 (`_build_serving "$pipeline_dir"`). Caught by grep verification.
- **Rule**: Before deleting a function, run `grep -rn "function_name" file` to find ALL call sites. Don't assume the function definition is the only reference.
- **Why**: Functions can be called from multiple places — the definition, the main loop, helper scripts. Missing one call site leaves a broken reference.

## 2026-03-23: cloudbuild.yaml serve image BASE_IMAGE should point to pipeline base, not base-python
- **Pattern**: The original cloudbuild.yaml had the serving image's `BASE_IMAGE` pointing to `base-python`. But the serve.Dockerfile uses `ARG BASE_IMAGE=base` which resolves to the pipeline's base image (not base-python). Updated to `${_PIPELINE}--base:${_TAG}`.
- **Rule**: Follow the Dockerfile's `ARG BASE_IMAGE=` declaration when setting Cloud Build `--build-arg`. The serve image extends the pipeline base (which has the framework + deps), not the bare base-python (which only has Python + uv).
- **Why**: If serve image extends base-python directly, it would lack the framework code, dependencies, and pipeline source — the serving app wouldn't work.

## 2026-03-23: mypy `import-untyped` is different from `import` — needs separate config
- **Pattern**: Installed `types-PyYAML` stubs and set `ignore_missing_imports = true` in mypy config, but still got `Library stubs not installed for "yaml" [import-untyped]`. The `ignore_missing_imports` flag only covers `[import]` errors, not `[import-untyped]`.
- **Rule**: When mypy reports `[import-untyped]` even after installing stubs, add `disable_error_code = ["import-untyped"]` to `[tool.mypy]` in pyproject.toml. This is a different error code from `[import]`.
- **Why**: mypy has two separate error codes for import issues: `import` (module not found) and `import-untyped` (module found but no type stubs). They require different config flags to suppress.

## 2026-03-23: Use `# type: ignore[specific-code]` — never bare `# type: ignore`
- **Pattern**: When fixing mypy errors with type ignore comments, always include the specific error code: `# type: ignore[attr-defined]`, `# type: ignore[no-any-return]`, `# type: ignore[assignment]`.
- **Rule**: Every `# type: ignore` MUST have a bracketed error code. Bare `# type: ignore` suppresses ALL mypy errors on that line, hiding real bugs.
- **Why**: A bare `# type: ignore` could mask a future type error that's unrelated to the original suppression. The specific code ensures only the known issue is suppressed.

## 2026-03-23: Parallelize Phase 8 with 3 background agents — independent file sets
- **Pattern**: Phase 8 had 7 tasks across 20+ files. Launched 3 background agents simultaneously: mypy fixes (7 framework files), DBTRun creation (3 new files), GCP exceptions + docs (10 files + 3 docs). Zero file overlap.
- **Rule**: For large phases, identify file sets with zero overlap and launch one agent per set. The constraint is never editing the same file from two agents. Use the main thread for quick fixes and verification.
- **Why**: Phase 8 wall-clock time was ~3 minutes instead of ~10. The agents worked on completely independent file sets. Final verification caught one remaining ruff error (line length) that was fixed in 10 seconds.

## 2026-03-23: Always run ruff after manual edits — auto-fix import sorting
- **Pattern**: Phase 6 introduced 2 import sorting errors (I001) from manually adding `from loguru import logger` and rearranging imports in smart_compiler.py. Caught by final verification, fixed with `ruff check --fix`.
- **Rule**: After any manual import change, run `uv run -- ruff check --fix` immediately rather than deferring to final verification. Catching sorting issues early prevents accumulation.
- **Why**: `ruff check --fix` for I001 is safe (only reorders, never changes logic) and takes <1 second. No reason to defer.
