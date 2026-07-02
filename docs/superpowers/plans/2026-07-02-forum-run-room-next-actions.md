# Forum Run Room Next Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic `next_actions` to run-room snapshots so operator and peer-tool surfaces know the recommended next move.

**Architecture:** Extend `forum.run_room.build_run_room` to compute the room sections once, then derive advisory actions from tasks, checkpoints, answer, and quality signals. CLI, HTTP, and MCP already expose the room payload, so no new surface plumbing is needed.

**Tech Stack:** Python 3.11, existing Forum run-room module and pytest.

## Global Constraints

- No new runtime dependencies.
- `build_run_room` remains read-only and appends no ledger entries.
- `next_actions` is advisory; no action execution is added.
- No duplicate retry actions for the same task.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `tests/test_run_room.py`: add next-action behavior tests.
- Modify `src/forum/run_room.py`: derive `next_actions` and include it in `room_text`.
- Modify `README.md`, `ARCHITECTURE.md`: document actionable run rooms.

---

### Task 1: Clean Run Export Action

**Files:**
- Modify: `tests/test_run_room.py`
- Modify: `src/forum/run_room.py`

**Interfaces:**
- Produces: `room["next_actions"]`

- [ ] **Step 1: Write failing clean-run action assertion**

Extend the existing joined-state room test to assert the room contains:

```python
{
    "id": "export-receipt",
    "kind": "export_receipt",
    "priority": "normal",
    "label": "Export run receipt",
    "reason": "answer is present and no blocking signals were detected",
    "target": {"answer_seq": answer.seq},
}
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_run_room.py::test_build_run_room_joins_current_run_state -q
```

Expected: FAIL because `next_actions` is missing.

- [ ] **Step 3: Implement initial `next_actions`**

Refactor `build_run_room` to compute `answer` first and return `next_actions=_next_actions(...)`. Add the clean export action when an answer exists and no blocking signals are present.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 2: Corrective Actions

**Files:**
- Modify: `tests/test_run_room.py`
- Modify: `src/forum/run_room.py`

**Interfaces:**
- Produces action kinds `retry_task`, `resume_from_checkpoint`, `revise_delivery`, `judge_intent`, `review_verification`, `raise_budget`.

- [ ] **Step 1: Write failing corrective-action tests**

Add tests for:

```python
def test_run_room_next_actions_retry_failed_task():
    ...
    assert room["next_actions"][0]["kind"] == "retry_task"
    assert room["next_actions"][0]["target"]["task_id"] == "T1"

def test_run_room_next_actions_surface_quality_and_resume_signals():
    ...
    kinds = [action["kind"] for action in room["next_actions"]]
    assert kinds == ["raise_budget", "resume_from_checkpoint", "revise_delivery", "judge_intent", "review_verification"]
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_run_room.py::test_run_room_next_actions_retry_failed_task tests/test_run_room.py::test_run_room_next_actions_surface_quality_and_resume_signals -q
```

Expected: FAIL because only clean export is implemented.

- [ ] **Step 3: Implement corrective actions**

Add `_next_actions`, `_action`, `_retry_actions`, and priority ordering. Do not duplicate retry actions when both result and verdict failed for the same task.

- [ ] **Step 4: Run green tests**

Run the same pytest command.

Expected: PASS.

---

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents actionable run rooms.

- [ ] **Step 1: Update docs**

Mention that run rooms include deterministic `next_actions`.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_run_room.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.
