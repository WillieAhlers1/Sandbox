# Lessons Learned

## 2026-03-20: Never push without explicit user confirmation
- **Pattern**: Pushed commits to remote without asking the user first.
- **Rule**: ALWAYS stop after `git commit` and ask before `git push`. Pushing affects shared state and is not reversible without force operations.
- **Why**: The user needs to review what's being pushed and confirm they're ready. Pushing is a high-impact action visible to others.

## 2026-03-20: Never overwrite existing docs/planning files
- **Pattern**: Overwrote the full 1100-line todo.md roadmap with a short Phase 1 checklist.
- **Rule**: NEVER use Write on existing documentation/planning files. Use Edit to add content, or create a SEPARATE file for task-specific tracking.
- **Why**: These files contain days of collaborative planning work. Overwriting destroys context that can't be regenerated. Always READ first, then APPEND or create alongside.

## 2026-03-20: Don't deprecate when you can delete
- **Pattern**: Phase 2 deprecated the old DAG system but kept 11 files "for backward compatibility." There were zero dag.py pipelines and nothing in production.
- **Rule**: If there are zero consumers and nothing deployed, DELETE immediately instead of deprecating. Dead code attracts confusion, not compatibility.
- **Why**: The deprecated code had import references scattered across 4 CLI files, caused 4 ruff errors, and confused the test structure. Phase 2.5 cleanup would have been unnecessary if we deleted in Phase 2.

## 2026-03-20: Fix Pydantic instance.model_fields → type(instance).model_fields
- **Pattern**: Accessing `model_fields` on a Pydantic instance (e.g., `step.component.model_fields`) works but is deprecated since Pydantic v2.11. Produces 19 DeprecationWarnings.
- **Rule**: Always use `type(obj).model_fields` instead of `obj.model_fields` when accessing Pydantic model field metadata.
- **Why**: Pydantic will remove instance-level `model_fields` access in v3.0. Using the class-level access is forward-compatible.

## 2026-03-20: Ruff must have zero errors — always check entire codebase
- **Pattern**: Fixed ruff errors only in files modified by the current phase, leaving pre-existing errors in utils/, feature_store/, etc.
- **Rule**: Per CLAUDE.md: "ENSURE RUFF HAS NO ERRORS WHEN EVER DEALING WITH PYTHON CODE." Run `uv run -- ruff check gcp_ml_framework/ tests/` against the entire codebase, not just changed files.
- **Why**: Selective ruff checking creates a broken-windows effect. Pre-existing errors accumulate and normalize sloppiness. Fixing everything now takes minutes; fixing later takes archaeology.

## 2026-03-20: Don't defer verification when prerequisites exist
- **Pattern**: Marked `gml context show` and `gml compile training_pipeline` as "deferred to Phase 4 — requires real .env" when a `.env` file with real GCP values already existed in the project.
- **Rule**: Before deferring a verification step, check if the prerequisites are already satisfied. If `.env` exists with real values, run the verification now.
- **Why**: Deferring tests that can run today means bugs hide longer. The .env had wrong variable names (`GCP_*` instead of `GML_GCP__*`) — running the test immediately would have caught this.

## 2026-03-20: Update init templates when the API changes
- **Pattern**: `gml init pipeline` still scaffolded code using the old `PipelineBuilder.ingest()` chain after the API moved to `Pipeline.add()`.
- **Rule**: When changing a public API, grep for the old API in ALL templates, examples, and documentation. `cmd_init.py` templates are code-generating code — they must use the current API.
- **Why**: New users scaffolding a pipeline would get code that doesn't match the architecture. First impressions matter.

## 2026-03-20: Don't add infra that can't be verified in the current environment
- **Pattern**: Added Terraform IAM bindings for Cloud Build SA to `terraform/envs/dev/main.tf` in a client sandbox where: (a) SAs are pre-provisioned and IAM module is already skipped, (b) `terraform apply` can't be run, (c) the default Cloud Build SA may already have sufficient permissions.
- **Rule**: Match infrastructure changes to the environment's reality. If the dev environment uses pre-existing SAs and skips IAM modules, don't add IAM bindings that follow a different pattern. Verify permissions at runtime (first `gml build`) and fix with `gcloud` commands if needed.
- **Why**: Aspirational Terraform that can't be applied creates false confidence and inconsistency. The existing comment "IAM module is not used — SAs are pre-provisioned" is the contract. Adding Cloud Build IAM alongside it contradicts the pattern.

## 2026-03-21: F-string brace escaping for Jinja2 templates in generated DAGs
- **Pattern**: SmartCompiler used 6 braces (`{{{{{{ ds }}}}}}`) in an f-string, producing `{{{ ds }}}` — invalid Jinja2. Airflow's template rendering fails with `TemplateSyntaxError: expected token ':', got '}'`.
- **Rule**: To emit `{{ ds }}` (valid Jinja2) from a Python f-string, use exactly 4 braces: `{{{{ ds }}}}`. Each `{{` in an f-string produces one literal `{`.
- **Why**: Triple braces `{{{ ds }}}` look like `{{` (Jinja2 expression start) + `{ ds }` (malformed dict literal) + `}` (extra). Jinja2 parses the inner `{` as a dict and fails when it sees `ds` without a `:`. The count is: 2n braces in f-string → n literal braces in output.

## 2026-03-20: Remove BuildKit cache mounts when targeting Cloud Build
- **Pattern**: Old Dockerfiles used `RUN --mount=type=cache,target=/root/.cache/uv` for local build caching. Cloud Build runs on ephemeral VMs — BuildKit cache mounts provide zero benefit and add complexity.
- **Rule**: When migrating from local Docker builds to Cloud Build, remove `--mount=type=cache` directives. Use `--cache-from` with AR `:latest` tags instead — this is the Cloud Build caching pattern.
- **Why**: BuildKit cache mounts only help when the build VM persists between builds. Cloud Build destroys the VM after each build. AR layer caching via `--cache-from` is the correct equivalent.
