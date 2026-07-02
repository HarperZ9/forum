# Forum Synthesis Result Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply `ContextBudget` to final synthesis result inputs while preserving full witnessed task outputs.

**Architecture:** Add a submit-level helper in `Orchestrator` that creates a prompt-only copy of `results` by applying `apply_context_budget("upstream", f"{task_id}->synthesizer", ...)` to each result output. The existing `ContextBudgetMeter` remains the run-wide token ledger. The real task result entries remain unchanged.

**Tech Stack:** Python 3.11, existing Forum ledger, context budget module, pytest.

## Global Constraints

- No new runtime dependencies.
- No changes to `ContextBudget` public fields.
- No mutation of original `Result` objects or result ledger payloads.
- `ContextBudget.max_total_tokens` remains global across all budgeted prompt surfaces.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `tests/test_context.py`: submit-level test for budgeted final synthesis inputs.
- Modify `src/forum/engine.py`: helper to budget prompt-only synthesis results and witness pressure entries.
- Modify `README.md`, `ARCHITECTURE.md`: document synthesis-stage budgeting.

---

### Task 1: Failing Submit-Level Synthesis Budget Test

**Files:**
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `ContextBudget(max_upstream_tokens=2)`
- Produces: failing test showing final synthesis currently receives full task output.

- [ ] **Step 1: Add the failing test**

Append this test to `tests/test_context.py`:

```python
def test_synthesis_result_budget_trims_prompt_but_keeps_full_result():
    from forum.context_budget import ContextBudget

    class _LongResultRecorder(_Recorder):
        async def run(self, assignment):
            self.prompts[assignment.agent] = assignment.instruction
            if assignment.agent == "backend":
                return Result(assignment.task_id, assignment.agent, "abcdefghijklmnop")
            return await super().run(assignment)

    rec = _LongResultRecorder()
    led, orch = _orch(rec)
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_upstream_tokens=2)))

    synth_prompt = rec.prompts["synthesizer"]
    assert "- T1: abcdefgh" in synth_prompt
    assert "abcdefghijklmnop" not in synth_prompt

    task_result = next(
        led.get_payload(e.payload_hash)
        for e in led.query(kind="result")
        if led.get_payload(e.payload_hash).get("id") == "T1"
    )
    assert task_result["output"] == "abcdefghijklmnop"

    budget_bodies = [led.get_payload(e.payload_hash) for e in led.query(kind="context_budget")]
    synth_budget = next(body for body in budget_bodies if body["label"] == "T1->synthesizer")
    assert synth_budget["source"] == "upstream"
    assert synth_budget["action"] == "trimmed"
    assert synth_budget["reason"] == "max_upstream_tokens"
    assert led.verify(deep=True) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_context.py::test_synthesis_result_budget_trims_prompt_but_keeps_full_result -q
```

Expected: FAIL because the synthesizer prompt still includes `abcdefghijklmnop`.

---

### Task 2: Budget Synthesis Inputs

**Files:**
- Modify: `src/forum/engine.py`

**Interfaces:**
- Consumes: `apply_context_budget`, `pressure_payload`, `ContextBudgetMeter`, `Result.witnessed_seq`
- Produces: `Orchestrator._budget_synthesis_results(...) -> dict[str, Result]`

- [ ] **Step 1: Add helper method**

Add a private method to `Orchestrator`:

```python
def _budget_synthesis_results(
    self,
    results: dict[str, Result],
    context_budget: ContextBudget | None,
    context_meter: ContextBudgetMeter,
    fallback_parent_seq: int,
) -> dict[str, Result]:
    if context_budget is None:
        return results
    budgeted: dict[str, Result] = {}
    for task_id, result in results.items():
        output, pressure = apply_context_budget(
            "upstream", f"{task_id}->synthesizer", result.output, context_budget, context_meter
        )
        if pressure.original_tokens > 0:
            self.ledger.append(
                actor="context-budget",
                kind="context_budget",
                payload=pressure_payload(pressure, context_budget, context_meter),
                causal_parent=result.witnessed_seq if result.witnessed_seq is not None else fallback_parent_seq,
            )
        budgeted[task_id] = dataclasses.replace(result, output=output)
    return budgeted
```

- [ ] **Step 2: Use helper before synthesis**

Change the synthesis call in `submit()` to compute:

```python
synthesis_results = self._budget_synthesis_results(results, context_budget, context_meter, req.seq)
```

Pass `synthesis_results` into `self.synthesizer.synthesize(...)`.

- [ ] **Step 3: Run the focused test**

Run:

```powershell
python -m pytest tests/test_context.py::test_synthesis_result_budget_trims_prompt_but_keeps_full_result -q
```

Expected: PASS.

---

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents final synthesis budgeting as part of token management.

- [ ] **Step 1: Update docs**

Mention that `ContextBudget` applies to request context, per-task context, inter-task upstream injection, and final synthesis result inputs.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_context.py tests/test_context_budget.py tests/test_dispatch.py tests/test_delivery.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.
