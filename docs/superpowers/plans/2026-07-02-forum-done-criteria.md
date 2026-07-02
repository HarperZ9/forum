# Forum Done Criteria Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional task-level done criteria that are sent to workers, witnessed in task entries, and used during validation.

**Architecture:** Extend the `Task` dataclass with a final optional `done_when` tuple and a `contract_instruction()` helper. Parse optional coordinator JSON fields into that tuple. Use the helper in dispatch and planned-run validation while preserving the original task instruction in ledger payloads.

**Tech Stack:** Python 3.11, existing Forum planner/dispatcher/control loop, pytest.

## Global Constraints

- No new runtime dependencies.
- Existing positional `Task(...)` constructors remain valid.
- Old coordinator JSON without `done_when` remains valid.
- Ledger task payloads keep the original `instruction` text and add `done_when` only when present.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `src/forum/plan.py`: add `Task.done_when` and `Task.contract_instruction()`.
- Modify `src/forum/control.py`: update coordinator prompt and parse optional `done_when`.
- Modify `src/forum/dispatch.py`: send contract instructions to workers and witness structured criteria.
- Modify `src/forum/engine.py`: validate planned task results against contract instructions.
- Modify `tests/test_plan.py`, `tests/test_coordinator.py`, `tests/test_dispatch.py`, `tests/test_engine.py`: regression coverage.
- Modify `README.md`, `ARCHITECTURE.md`: document done criteria.

---

### Task 1: Task Contract Formatting

**Files:**
- Modify: `tests/test_plan.py`
- Modify: `src/forum/plan.py`

**Interfaces:**
- Produces: `Task.done_when: tuple[str, ...]`
- Produces: `Task.contract_instruction() -> str`

- [ ] **Step 1: Write failing tests**

Add tests asserting that a task with no criteria returns the original instruction and a task with criteria returns the instruction plus a `Done criteria:` bullet block.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_plan.py::test_task_contract_instruction_defaults_to_instruction tests/test_plan.py::test_task_contract_instruction_includes_done_criteria -q
```

Expected: FAIL because `Task` has no `done_when` or `contract_instruction`.

- [ ] **Step 3: Implement the dataclass field and helper**

Add `done_when: tuple[str, ...] = ()` as the final field and implement `contract_instruction()`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 2: Coordinator Parses Criteria

**Files:**
- Modify: `tests/test_coordinator.py`
- Modify: `src/forum/control.py`

**Interfaces:**
- Consumes: optional JSON field `done_when`
- Produces: `Task.done_when`

- [ ] **Step 1: Write failing coordinator test**

Add a JSON plan with `"done_when": ["unit tests pass", "docs mention the endpoint"]` and assert the parsed task has that tuple.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_coordinator.py::test_coordinator_parses_done_when -q
```

Expected: FAIL because the field is ignored.

- [ ] **Step 3: Implement parser and prompt update**

Add `_parse_done_when(raw: object) -> tuple[str, ...]` and call it when constructing `Task`. Update `_COORDINATOR_PROMPT` to show the optional field.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 3: Dispatch Witnesses and Sends Criteria

**Files:**
- Modify: `tests/test_dispatch.py`
- Modify: `src/forum/dispatch.py`

**Interfaces:**
- Consumes: `Task.contract_instruction()`
- Produces: task prompt with criteria and task ledger payload with optional `done_when`

- [ ] **Step 1: Write failing dispatch test**

Create a task with `done_when=("tests pass", "migration documented")`, run it with the echoing executor, and assert the worker output includes the criteria block. Assert the ledger task payload keeps `instruction == "build"` and has `done_when == ["tests pass", "migration documented"]`.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_dispatch.py::test_done_criteria_are_sent_to_worker_and_witnessed -q
```

Expected: FAIL because dispatch sends only the raw instruction and does not witness `done_when`.

- [ ] **Step 3: Implement dispatch integration**

Use `task.contract_instruction()` as the base instruction in both upstream augmentation helpers. Build the task ledger payload as a dict and add `done_when` when present.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 4: Validation Uses Criteria

**Files:**
- Modify: `tests/test_engine.py`
- Modify: `src/forum/engine.py`

**Interfaces:**
- Consumes: `Task.contract_instruction()`
- Produces: validator prompt includes criteria for planned submit runs

- [ ] **Step 1: Write failing engine test**

Use a scripted executor whose coordinator returns a task with `done_when`, capture validator assignments, and assert the validator prompt includes `Done criteria:` and the criterion text.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_engine.py::test_submit_validates_against_done_criteria -q
```

Expected: FAIL because validation receives only the raw instruction.

- [ ] **Step 3: Implement validation integration**

In planned submit validation and escalation retry validation, pass `task.contract_instruction()` to `_witness_verdict`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 5: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents done criteria as explicit task stop contracts.

- [ ] **Step 1: Update docs**

Mention optional task-level `done_when` criteria in the plan/dispatch and run-contract sections.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_plan.py tests/test_coordinator.py tests/test_dispatch.py tests/test_engine.py tests/test_budget.py tests/test_escalation.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.
