# Forum Tiered Executor Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tier-aware local executor selection so roster `model_tier` policy can choose cheap, capable, or frontier runtimes per task.

**Architecture:** Create `forum.runtime.TieredExecutor` as a wrapper over the existing executor seam. Add `assignment_model_id(executor, assignment)` so dispatch can witness the selected per-task runtime while old executors keep their current global identity. Wire CLI tier command flags into `_make_executor` without changing existing single-executor behavior.

**Tech Stack:** Python 3.11, existing Forum executor protocol, roster, dispatch, CLI argparse, pytest.

## Global Constraints

- No new runtime dependencies.
- Existing `--cmd`, `--chat-url`, and `--api` behavior remains unchanged when no tier flags are present.
- Unknown agents and control roles fall back to the default executor.
- Result entries must witness the actual selected executor model id for task calls.

---

## File Structure

- Create `src/forum/runtime.py`: `TieredExecutor` and tier command helper boundaries.
- Modify `src/forum/executor.py`: add `assignment_model_id`.
- Modify `src/forum/dispatch.py`: record assignment-aware model ids.
- Modify `src/forum/cli.py`: parse and build tier command executors.
- Modify `tests/test_runtime.py`: pure tier selection behavior.
- Modify `tests/test_dispatch.py`: ledger attribution for selected task runtimes.
- Modify `tests/test_cli.py`: parser and `_make_executor` behavior for tier flags.
- Modify `README.md`, `ARCHITECTURE.md`: document tiered runtime selection.

---

### Task 1: TieredExecutor Pure Selection

**Files:**
- Create: `tests/test_runtime.py`
- Create: `src/forum/runtime.py`

**Interfaces:**
- Produces: `TieredExecutor(roster, default_executor, tiers: dict[str, Executor] | None = None)`
- Produces: `TieredExecutor.select(assignment: Assignment) -> Executor`
- Produces: `TieredExecutor.model_id_for(assignment: Assignment) -> str`

- [ ] **Step 1: Write failing tests**

Create `tests/test_runtime.py`:

```python
import asyncio

from forum.executor import Assignment, Result
from forum.roster import load_default
from forum.runtime import TieredExecutor


class _Named:
    def __init__(self, model_id):
        self.model_id = model_id
        self.calls = []

    async def run(self, assignment):
        self.calls.append(assignment)
        return Result(assignment.task_id, assignment.agent, self.model_id)


def test_tiered_executor_selects_by_roster_model_tier():
    roster = load_default()
    default = _Named("default-local")
    cheap = _Named("cheap-local")
    capable = _Named("capable-local")
    frontier = _Named("frontier-local")
    ex = TieredExecutor(
        roster,
        default,
        tiers={"cheap": cheap, "capable": capable, "frontier": frontier},
    )

    backend = Assignment("T1", "backend", "build")
    docs = Assignment("T2", "technical-writing", "docs")
    foundry = Assignment("T3", "model-foundry", "eval")
    control = Assignment("control:coordinator", "coordinator", "plan")

    assert ex.select(backend) is capable
    assert ex.select(docs) is cheap
    assert ex.select(foundry) is frontier
    assert ex.select(control) is default
    assert ex.model_id_for(backend) == "capable-local"
    assert ex.model_id_for(control) == "default-local"


def test_tiered_executor_runs_selected_executor():
    roster = load_default()
    default = _Named("default-local")
    capable = _Named("capable-local")
    ex = TieredExecutor(roster, default, tiers={"capable": capable})

    result = asyncio.run(ex.run(Assignment("T1", "backend", "build api")))

    assert result.output == "capable-local"
    assert capable.calls[0].instruction == "build api"
    assert default.calls == []
```

- [ ] **Step 2: Run red tests**

```powershell
python -m pytest tests/test_runtime.py -q
```

Expected: FAIL because `forum.runtime` does not exist.

- [ ] **Step 3: Implement minimal runtime module**

Create `src/forum/runtime.py` with `TieredExecutor` selecting by roster
`model_tier`, falling back to default, and delegating `run`.

- [ ] **Step 4: Run green tests**

```powershell
python -m pytest tests/test_runtime.py -q
```

Expected: PASS.

---

### Task 2: Dispatch Model Attribution

**Files:**
- Modify: `tests/test_dispatch.py`
- Modify: `src/forum/executor.py`
- Modify: `src/forum/dispatch.py`

**Interfaces:**
- Produces: `assignment_model_id(executor, assignment) -> str`

- [ ] **Step 1: Write failing dispatch test**

Append to `tests/test_dispatch.py`:

```python
def test_dispatch_records_selected_tier_model_identity():
    from forum.executor import Result
    from forum.roster import load_default
    from forum.runtime import TieredExecutor

    class _Named:
        def __init__(self, model_id):
            self.model_id = model_id

        async def run(self, assignment):
            return Result(assignment.task_id, assignment.agent, assignment.instruction)

    ledger = make_ledger()
    plan = Plan((
        Task("T1", "backend", "build", ()),
        Task("T2", "technical-writing", "docs", ()),
    ))
    executor = TieredExecutor(
        load_default(),
        _Named("default-local"),
        tiers={"capable": _Named("capable-local"), "cheap": _Named("cheap-local")},
    )

    asyncio.run(dispatch_plan(plan, ledger, executor, max_parallel=2))

    models = {
        body["id"]: body["model"]
        for body in (ledger.get_payload(e.payload_hash) for e in ledger.query(kind="result"))
    }
    assert models == {"T1": "capable-local", "T2": "cheap-local"}
```

- [ ] **Step 2: Run red test**

```powershell
python -m pytest tests/test_dispatch.py::test_dispatch_records_selected_tier_model_identity -q
```

Expected: FAIL because dispatch records the wrapper identity.

- [ ] **Step 3: Implement assignment-aware model identity**

Add `assignment_model_id` to `src/forum/executor.py` and use it in
`src/forum/dispatch.py` for result payloads.

- [ ] **Step 4: Run green test**

```powershell
python -m pytest tests/test_dispatch.py::test_dispatch_records_selected_tier_model_identity -q
```

Expected: PASS.

---

### Task 3: CLI Tier Command Flags

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/forum/cli.py`

**Interfaces:**
- Consumes: `TieredExecutor`
- Produces parser args `cheap_cmd`, `capable_cmd`, `frontier_cmd`

- [ ] **Step 1: Write failing CLI tests**

Add to `tests/test_cli.py`:

```python
def test_tier_command_flags_parse_and_wrap_base_executor():
    from forum.executor import Assignment
    from forum.runtime import TieredExecutor

    args = build_parser().parse_args([
        "submit", "do x",
        "--cmd", "base-model",
        "--cheap-cmd", "cheap-model",
        "--capable-cmd", "capable-model",
    ])
    executor = _make_executor(args)

    assert isinstance(executor, TieredExecutor)
    assert executor.select(Assignment("control:coordinator", "coordinator", "plan"))._command == ["base-model"]
    assert executor.select(Assignment("T1", "backend", "build"))._command == ["capable-model"]
    assert executor.select(Assignment("T2", "technical-writing", "docs"))._command == ["cheap-model"]


def test_tier_command_flags_can_supply_default_without_cmd():
    from forum.executor import Assignment
    from forum.runtime import TieredExecutor

    args = build_parser().parse_args([
        "submit", "do x",
        "--capable-cmd", "capable-model",
    ])
    executor = _make_executor(args)

    assert isinstance(executor, TieredExecutor)
    assert executor.select(Assignment("control:coordinator", "coordinator", "plan"))._command == ["capable-model"]
```

- [ ] **Step 2: Run red tests**

```powershell
python -m pytest tests/test_cli.py::test_tier_command_flags_parse_and_wrap_base_executor tests/test_cli.py::test_tier_command_flags_can_supply_default_without_cmd -q
```

Expected: FAIL because the flags do not exist.

- [ ] **Step 3: Implement CLI parsing and executor construction**

Add tier flags to `_add_executor`. Refactor `_make_executor` with helpers that
create `SubprocessExecutor` instances and wrap the base executor with
`TieredExecutor(load_default(), base, tiers=tier_map)` when tier commands are
provided.

- [ ] **Step 4: Run green tests**

```powershell
python -m pytest tests/test_cli.py::test_tier_command_flags_parse_and_wrap_base_executor tests/test_cli.py::test_tier_command_flags_can_supply_default_without_cmd -q
```

Expected: PASS.

---

### Task 4: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Update docs**

Document `TieredExecutor` and `--cheap-cmd` / `--capable-cmd` /
`--frontier-cmd` as the first executable local runtime consumer of roster tier
policy.

- [ ] **Step 2: Run targeted tests**

```powershell
python -m pytest tests/test_runtime.py tests/test_dispatch.py tests/test_cli.py tests/test_engine.py tests/test_http_surface.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```powershell
python -m pytest -q
```

Expected: PASS.
