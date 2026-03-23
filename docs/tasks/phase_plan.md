# Implementation Plan: Loop/Condition Operators + Verification Pipeline Update

## Context

REQS 22.0 [P0]: Data scientists train models per brand/market/channel. They need loop operators to reuse pipeline steps. This plan implements `for_each()` and `condition()` on the Pipeline builder, with KFP compilation support.

Additionally, the verification pipeline is updated to exercise ALL framework capabilities: looping, conditionals, DBTRun, monitoring, mixed @task/@ml_task.

**Critical finding:** `dsl.Condition` is DEPRECATED in KFP v2. Use `dsl.If` / `dsl.Elif` / `dsl.Else` instead.

**Baseline:** 0 failed, 244 passed | 0 ruff | 0 mypy

---

## Part 1: Loop/Condition Implementation

### Architecture: Minimal Changes

The design follows the existing pattern — the builder captures intent, the compiler generates KFP code, the smart compiler validates Airflow constraints.

**Files modified (4):**
- `gcp_ml_framework/pipeline/builder.py` — add `for_each()`, `condition()`, new data models
- `gcp_ml_framework/pipeline/compiler.py` — add `dsl.ParallelFor` / `dsl.If` wrapping
- `gcp_ml_framework/pipeline/smart_compiler.py` — add validation (no @task in loops/conditions)
- `gcp_ml_framework/__init__.py` — export new symbols if needed

**Files created (2):**
- `tests/pipeline/test_builder_loops.py` — builder unit tests
- `tests/pipeline/test_compiler_loops.py` — compiler unit tests

**Files unchanged:** BaseComponent, all components, decorators, naming, config, context, CLI, scripts.

---

### Task 1: Data Models (builder.py)

Add two Pydantic models to represent control flow blocks:

```python
class LoopBlock(BaseModel):
    """A for_each loop over items."""
    model_config = {"arbitrary_types_allowed": True}

    items: list[str]
    item_param: str          # which component field receives the loop variable
    steps: list[PipelineStep]
    index: int               # ordinal within pipeline

class ConditionBlock(BaseModel):
    """A conditional block with then/else branches."""
    model_config = {"arbitrary_types_allowed": True}

    # Reference to the step whose output is checked
    source_step: str         # name of the step producing the output to check
    output_key: str          # KFP output name (e.g., "output_uri")
    operator: str            # "==", "!=", ">", "<", ">=", "<="
    value: str               # comparison value
    then_steps: list[PipelineStep]
    else_steps: list[PipelineStep] = Field(default_factory=list)
    index: int
```

Add fields to `PipelineDefinition`:
```python
    loop_blocks: list[LoopBlock] = Field(default_factory=list)
    condition_blocks: list[ConditionBlock] = Field(default_factory=list)
```

Add property:
```python
    @property
    def has_control_flow(self) -> bool:
        return bool(self.loop_blocks or self.condition_blocks)
```

### Task 2: Builder Methods (builder.py)

Add to `Pipeline` class:

```python
def for_each(
    self,
    items: list[str],
    steps: list[BaseComponent],
    *,
    item_param: str = "loop_item",
    names: list[str] | None = None,
) -> Pipeline:
    """Loop over items, running steps for each.

    Each step component must be @ml_task. @task steps (Airflow operators)
    cannot be dynamically unrolled at compile time.

    Args:
        items: List of string items to iterate over.
        steps: Components to run for each item.
        item_param: Name of the component field that receives the loop variable.
            The data scientist must declare this field on their component subclass.
        names: Optional step names (auto-generated if not provided).

    Example:
        @ml_task
        class BrandTrainer(TrainModel):
            brand: str = ""
            def run(self) -> Path: ...

        pipeline = (
            Pipeline(name="multi_brand")
            .for_each(
                items=["brand_a", "brand_b"],
                steps=[BrandTrainer(component_name="train")],
                item_param="brand",
            )
            .build()
        )
    """
    pipeline_steps = []
    for i, comp in enumerate(steps):
        step_name = names[i] if names and i < len(names) else f"loop_{len(self._loop_blocks)}_{type(comp).__name__}_{i}"
        task_type = getattr(comp, "task_type", TaskType.ML_TASK)
        if task_type != TaskType.ML_TASK:
            raise ValueError(
                f"for_each() only supports @ml_task components. "
                f"'{type(comp).__name__}' is @task — Airflow operators "
                f"cannot be dynamically unrolled at compile time."
            )
        pipeline_steps.append(PipelineStep(name=step_name, component=comp, task_type=task_type))

    self._loop_blocks.append(LoopBlock(
        items=items,
        item_param=item_param,
        steps=pipeline_steps,
        index=len(self._loop_blocks),
    ))
    return self


def condition(
    self,
    *,
    source_step: str,
    output_key: str = "output_uri",
    operator: str = "!=",
    value: str = "",
    then_steps: list[BaseComponent],
    else_steps: list[BaseComponent] | None = None,
    then_names: list[str] | None = None,
    else_names: list[str] | None = None,
) -> Pipeline:
    """Conditional execution based on a prior step's output.

    Only @ml_task steps are supported in then/else branches.

    Args:
        source_step: Name of the step whose output to check.
        output_key: KFP output key to check (default: "output_uri").
        operator: Comparison operator ("==", "!=", ">", "<", ">=", "<=").
        value: Value to compare against.
        then_steps: Components to run if condition is true.
        else_steps: Components to run if condition is false (optional).
    """
    # Build then PipelineSteps (validate @ml_task)
    then_pipeline_steps = _build_steps(then_steps, then_names, f"cond_{len(self._condition_blocks)}_then", self)
    else_pipeline_steps = _build_steps(else_steps or [], else_names, f"cond_{len(self._condition_blocks)}_else", self) if else_steps else []

    self._condition_blocks.append(ConditionBlock(
        source_step=source_step,
        output_key=output_key,
        operator=operator,
        value=value,
        then_steps=then_pipeline_steps,
        else_steps=else_pipeline_steps,
        index=len(self._condition_blocks),
    ))
    return self
```

Update `Pipeline.__init__`:
```python
    self._loop_blocks: list[LoopBlock] = []
    self._condition_blocks: list[ConditionBlock] = []
```

Update `Pipeline.build()`:
```python
    return PipelineDefinition(
        name=self._name,
        schedule=self._schedule,
        steps=list(self._steps),
        loop_blocks=list(self._loop_blocks),
        condition_blocks=list(self._condition_blocks),
        description=self._description,
        tags=self._tags,
    )
```

Note: `build()` validation relaxed — allow empty `steps` if there are loop_blocks or condition_blocks.

### Task 3: Compiler Changes (compiler.py)

In `_build_kfp_pipeline()`, after the main step loop (line 174), add loop/condition compilation:

```python
        # ── Loop blocks: dsl.ParallelFor ──────────────────────
        for loop_block in pipeline_def.loop_blocks:
            with dsl.ParallelFor(
                items=loop_block.items,
                name=f"loop_{loop_block.index}",
            ) as loop_item:
                loop_prev = prev_task  # chain after last sequential step
                for step in loop_block.steps:
                    step_module = step.component.__class__.__module__
                    step_image = self._resolve_image_uri(context, step.component.runtime_dockerfile)
                    component_fn = step.component.as_kfp_component(
                        step_module=step_module, base_image=step_image,
                    )
                    step_extra = derived_params.get(step.name, {})
                    merged = {**component_fields_for(step), **ctx_params, **step_extra}
                    merged["run_date"] = run_date
                    # Inject loop variable
                    merged[loop_block.item_param] = loop_item

                    call_kwargs = filter_and_serialize(merged, component_fn)
                    task = component_fn(**call_kwargs)
                    task.set_display_name(step.name)
                    if loop_prev is not None:
                        task.after(loop_prev)
                    loop_prev = task

        # ── Condition blocks: dsl.If ──────────────────────────
        for cond_block in pipeline_def.condition_blocks:
            # Find the source task by name
            source_task = task_registry[cond_block.source_step]

            # Build comparison expression
            condition_expr = _build_condition_expr(
                source_task, cond_block.output_key,
                cond_block.operator, cond_block.value,
            )

            with dsl.If(condition_expr, name=f"condition_{cond_block.index}"):
                cond_prev = source_task
                for step in cond_block.then_steps:
                    # ... same compilation as main loop

            if cond_block.else_steps:
                with dsl.Else():
                    for step in cond_block.else_steps:
                        # ... same compilation
```

**Key helpers to extract (DRY):**
- `_compile_step(step, context, ctx_params, derived_params, prev_task)` — extracts the per-step compilation logic from lines 100-173 into a reusable method
- `_build_condition_expr(task, output_key, operator, value)` — converts operator string to KFP comparison

**Task registry:** Add `task_registry: dict[str, Any] = {}` to track tasks by name during compilation, so conditions can reference prior steps.

### Task 4: SmartCompiler Validation (smart_compiler.py)

In `compile()`, before delegating to PipelineCompiler, validate:

```python
def compile(self, pipeline_def, context, pipeline_dir=None):
    # Validate: no @task steps in loop/condition blocks
    for loop_block in pipeline_def.loop_blocks:
        for step in loop_block.steps:
            if step.task_type == TaskType.TASK:
                raise NotImplementedError(
                    f"for_each() only supports @ml_task steps. "
                    f"'{step.name}' is @task (Airflow operator) — "
                    f"cannot be dynamically unrolled at compile time."
                )
    for cond_block in pipeline_def.condition_blocks:
        for step in cond_block.then_steps + cond_block.else_steps:
            if step.task_type == TaskType.TASK:
                raise NotImplementedError(
                    f"condition() only supports @ml_task steps. "
                    f"'{step.name}' is @task (Airflow operator)."
                )

    # ... existing compilation logic
```

### Task 5: Tests

**`tests/pipeline/test_builder_loops.py`** (~100 lines):
- `test_for_each_returns_self` — fluent API
- `test_for_each_captures_items` — items stored in LoopBlock
- `test_for_each_rejects_task_components` — @task raises ValueError
- `test_for_each_accepts_ml_task_components` — @ml_task works
- `test_condition_returns_self` — fluent API
- `test_condition_captures_source_step` — references stored correctly
- `test_condition_rejects_task_components` — @task raises ValueError
- `test_build_with_loop_blocks` — PipelineDefinition has loop_blocks
- `test_build_with_condition_blocks` — PipelineDefinition has condition_blocks
- `test_has_control_flow_property` — True when loops/conditions present

**`tests/pipeline/test_compiler_loops.py`** (~80 lines):
- `test_loop_produces_valid_yaml` — KFP compile succeeds with loop
- `test_condition_produces_valid_yaml` — KFP compile succeeds with condition
- `test_smart_compiler_rejects_task_in_loop` — NotImplementedError raised

---

## Part 2: Verification Pipeline Update

### Goal
Update `pipelines/verification_pipeline/pipeline.py` to exercise ALL framework capabilities in one pipeline.

### New Structure
```
BQQuery (@task)        ── ingest raw data
  ↓
BQTransform (@task)    ── transform features
  ↓
DBTRun (@task)         ── run dbt models (demonstrates 19.0)
  ↓
[ML_TASK group via SmartCompiler]:
  TrainVerifyModelStep (@ml_task)  ── train
  EvaluateVerifyStep (@ml_task)    ── evaluate with gates
  RegisterModel (@ml_task)         ── register with serving image
  DeployModel (@ml_task)           ── deploy with monitoring (demonstrates monitoring)
```

**Note on loops/conditions in verification pipeline:** The verification pipeline is a MIXED pipeline (@task + @ml_task). Loops/conditions only work with pure @ml_task steps and are compiled INTO the KFP YAML. The SmartCompiler wraps the ML group as a `RunPipelineJobOperator` — the loop/condition lives INSIDE the KFP YAML, not in the Airflow DAG.

So loops/conditions are exercised in the PipelineCompiler layer, which handles the ML group. The verification pipeline already has an ML group — we can add a `for_each` WITHIN that group.

However, this creates a complexity: the current `for_each()` API adds steps to `loop_blocks` separate from `steps`. The SmartCompiler would need to detect that the loop_blocks contain @ml_task steps and include them in the KFP YAML compilation.

**Simpler approach for verification:** Create a SEPARATE pure @ml_task pipeline for loop/condition testing, and update the verification pipeline to add DBTRun + monitoring. Don't force loop/condition into the mixed verification pipeline.

### Files Modified
- `pipelines/verification_pipeline/pipeline.py` — add DBTRun step, ensure monitoring fields
- `tests/verification_pipeline/test_compile.py` — update assertions for new structure

### Files Created
- `pipelines/verification_pipeline/steps/__init__.py` — if missing
- NO new pipeline needed for loops — tested via unit tests

---

## Part 3: Execution Order

1. **Task 1-2:** Builder data models + methods (builder.py)
2. **Task 5a:** Builder tests (test_builder_loops.py) — TDD: write tests first
3. **Task 3:** Compiler changes (compiler.py) — extract DRY helper, add loop/condition
4. **Task 4:** SmartCompiler validation (smart_compiler.py)
5. **Task 5b:** Compiler tests (test_compiler_loops.py)
6. **Verification pipeline update** — add DBTRun, verify monitoring
7. **Ruff + mypy + full test suite**

---

## Part 4: Verification

```bash
# 1. New builder tests
uv run -- pytest tests/pipeline/test_builder_loops.py -m unit -v

# 2. New compiler tests
uv run -- pytest tests/pipeline/test_compiler_loops.py -m unit -v

# 3. SmartCompiler validation test
uv run -- pytest tests/pipeline/test_smart_compiler.py -m unit -v

# 4. Verification pipeline compiles
UV_ENV_FILE=.env uv run -- gml compile verification_pipeline

# 5. Full suite
uv run -- ruff check gcp_ml_framework tests
uv run -- mypy gcp_ml_framework/
uv run -- pytest tests/ -m unit --tb=no -q
```

---

## Part 5: What This Does NOT Do (Explicit Scope)

| Not in scope | Why |
|--------------|-----|
| @task loops (Airflow `TaskFlow.map()`) | Airflow 2.4+ feature, complex, different compilation path |
| Nested loops (loop inside loop) | KFP supports it but adds complexity; defer to future |
| Dynamic items from prior step outputs | Items must be static strings for now |
| Condition with `dsl.Elif` / `dsl.Else` chains | MVP: just `if/then`, `else` optional |
| LocalRunner loop/condition support | Only KFP compilation; `--local` runs steps sequentially |

---

## Key Design Decisions

1. **`item_param` is explicit** — data scientist declares which field receives the loop variable. No BaseComponent pollution.
2. **`dsl.If` not `dsl.Condition`** — KFP v2 deprecated `dsl.Condition`, use `dsl.If`/`dsl.Else`.
3. **Validation at build time** — `for_each()` rejects @task components immediately, not at compile time.
4. **Loop/condition blocks are separate from `steps`** — not interleaved in the sequential step list.
5. **DRY compiler** — extract step compilation into `_compile_step()` helper, reuse for main loop, for_each loop, and condition branches.
