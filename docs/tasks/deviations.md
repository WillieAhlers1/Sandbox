# Deviations from Planning Documents

**Date:** 2026-03-21
**Scope:** Phases 1-5.5 implementation vs. REQS.docx, discussion.md, decisions.md

---

## Summary

The implementation is **95% aligned** with documented requirements. All 22 REQS items are accounted for (14 complete, 8 properly deferred to phases 6-8). All ADRs (1-11) are implemented or properly deferred. One significant addition was made that was not in the original planning documents.

---

## Deviation 1: Phase 5.5 — Dedicated Serving Image (CPR)

**Severity:** Addition (not a violation — adds capability not in original scope)

### What the documents say

- **REQS.docx:** No requirement for Custom Prediction Routines or serving containers
- **discussion.md Section 9:** Phase 5 = "Complete pipeline + experiment tracking" — no mention of serving images
- **decisions.md:** No ADR for serving container architecture
- **todo.md Phase 5 Definition of Done (line 1491-1506):** Does not list serving image work

### What phase_plan.md says (risk section)

> **Risk:** HousePredictionModel.predict() returns DataFrame (not ndarray). Verify Vertex AI pre-built sklearn container handles this during E2E. If not, use Custom Prediction Routine (CPR) container or adjust model interface.

### What was implemented

A full serving image system was built as Phase 5.5:
- `gcp_ml_framework/serving/handler.py` — HTTP prediction server implementing Vertex AI CPR protocol
- `docker/serving/Dockerfile` — Slim serving image (~200MB vs full pipeline image)
- `cloudbuild.yaml` Steps 6-8 — Build and push `{pipeline}-serving` images
- `compiler.py` — Auto-defaults RegisterModel/DeployModel to serving image
- `register.py` + `vertex.py` — CPR routes (`/predict`, `/health`, command, ports) for custom containers
- `scripts/docker_build.sh` — Serving image build for local path
- `tests/serving/test_handler.py` — 8 handler tests
- Updated compiler, register, and vertex tests with CPR assertions

### Why this was done

Vertex AI logs showed `ModuleNotFoundError: No module named 'second_run'` when the pre-built `sklearn-cpu.1-3:latest` container tried to unpickle `HousePredictionModel`. The model uses custom classes from the `second_run` package, which the pre-built container cannot resolve. This is a **blocking production issue** — models register but cannot serve predictions.

### Classification

**Justified operational fix.** The CPR system was listed as a contingency in phase_plan.md and proved necessary during E2E validation. However, it should have been:
1. Documented as an ADR (ADR-012)
2. Added to the todo.md Phase 5 Definition of Done
3. Tracked as a sub-phase in the roadmap

### Impact

- 3 new files in framework code (serving module)
- 1 new Dockerfile
- cloudbuild.yaml extended (3 additional steps)
- 6 existing files modified
- 16 new tests (handler + CPR assertions)
- Both serving images built and deployed to Artifact Registry

---

## Deviation 2: Docker Hierarchy Now 3-Layer (Not 2-Layer)

**Severity:** Minor architectural divergence

### What the documents say

- **ADR-011 (decisions.md):** "Simplify to 2 layers: base-python → {pipeline-name}"
- **discussion.md Decision 9:** "Simplify to 2 layers"

### What was implemented

With Phase 5.5, the hierarchy is now:
```
base-python:tag
  ├── {pipeline}:tag              (training — full deps + source)
  └── {pipeline}-serving:tag      (serving — slim, runtime deps only)
```

This is a **3-image hierarchy** (1 base + 2 derived per pipeline), not 2.

### Why this is acceptable

The serving image is a separate concern from the pipeline image — it serves predictions, not training. The ADR's intent was to eliminate the 4-layer `base-python → component-base → base-ml → pipeline` hierarchy, which was achieved. The serving image is a new leaf, not an intermediate layer.

---

## Deviation 3: Unchecked Item in Phase 5 Definition of Done

**Severity:** Documentation-only (code is correct)

### What todo.md says (line 1506)

```
- [ ] DeployModel.run() passes monitoring fields through to run_deploy()
```

### What was actually implemented

`DeployModel.run()` at `gcp_ml_framework/components/ml/deploy.py:54-72` passes all 6 monitoring fields:
- `enable_monitoring`
- `monitoring_alert_email`
- `monitoring_log_sample_rate`
- `monitoring_monitor_interval`
- `monitoring_skew_thresholds`
- `monitoring_drift_thresholds`

Tests verify this works (`tests/components/test_deploy.py`, `tests/utils/test_vertex.py`).

### Fix

Mark the checkbox as `[x]` in todo.md.

---

## Items NOT Deviating (Properly Deferred to Phases 6-8)

These items appear in REQS.docx/discussion.md but are **correctly scheduled** for future phases:

| Item | Document | Scheduled Phase |
|------|----------|----------------|
| REQS 3.0 — Cleanout Invalid DAGs | REQS.docx | Phase 8 |
| REQS 9.0 — Structured Logging | REQS.docx | Phase 8 |
| REQS 10.0 — Google-Style Docstrings | REQS.docx | Phase 8 |
| REQS 14.0 — Standard Variables in Containers | REQS.docx | Phase 6 |
| REQS 17.0 — Mypy Annotations | REQS.docx | Phase 8 |
| REQS 19.0 — DBT Integration | REQS.docx | Phase 7 |
| REQS 20.0 — AGENTS.md | REQS.docx | Phase 8 |
| REQS 22.0 — Conditional/Loop Operators | REQS.docx | Phase 6 |
| ADR-010 — Cost Labels on GCP Resources | decisions.md | Phase 8 |
