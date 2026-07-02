# Forum Submit Wave Checkpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose existing dispatcher per-wave checkpoints through high-level submit APIs.

**Architecture:** Add a `checkpoint_each_wave` boolean to `Orchestrator.submit`, pass it into `dispatch_plan`, then route the same flag through CLI, HTTP, and MCP submit surfaces. Keep checkpoint payload format unchanged.

**Tech Stack:** Python 3.11, existing Forum dispatch checkpoints, CLI argparse, HTTP surface, MCP surface, pytest.

## Global Constraints

- No new runtime dependencies.
- Default behavior remains unchanged.
- Checkpoint ledger entries keep their existing shape.
- MCP continues to route through HTTP so surfaces do not drift.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `src/forum/engine.py`: add submit parameter and pass-through.
- Modify `src/forum/cli.py`: add `--checkpoint-each-wave` and pass-through.
- Modify `src/forum/http_surface.py`: parse and validate `checkpoint_each_wave`.
- Modify `src/forum/mcp_surface.py`: add schema/property forwarding.
- Modify `tests/test_engine.py`, `tests/test_cli.py`, `tests/test_http_surface.py`, `tests/test_mcp_surface.py`: regression coverage.
- Modify `README.md`, `ARCHITECTURE.md`: document phase savepoints on submit.

---

### Task 1: Engine Submit Checkpoints

**Files:**
- Modify: `tests/test_engine.py`
- Modify: `src/forum/engine.py`

**Interfaces:**
- Produces: `Orchestrator.submit(..., checkpoint_each_wave: bool = False)`

- [ ] **Step 1: Write failing engine test**

Use a scripted executor whose coordinator returns two dependent tasks. Call `submit(..., checkpoint_each_wave=True)` and assert two `checkpoint` entries are present.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_engine.py::test_submit_can_checkpoint_each_wave -q
```

Expected: FAIL because `submit` does not accept the parameter.

- [ ] **Step 3: Implement pass-through**

Add the parameter and pass it to `dispatch_plan(..., checkpoint_each_wave=checkpoint_each_wave)`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 2: CLI Flag

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/forum/cli.py`

**Interfaces:**
- Produces: `forum submit --checkpoint-each-wave`

- [ ] **Step 1: Write failing CLI parse test**

Assert `build_parser().parse_args(["submit", "do x", "--cmd", "echo", "--checkpoint-each-wave"]).checkpoint_each_wave is True`.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_cli.py::test_submit_checkpoint_each_wave_flag_parses -q
```

Expected: FAIL because the flag is unknown.

- [ ] **Step 3: Implement CLI flag and pass-through**

Add the argparse flag and pass `checkpoint_each_wave=args.checkpoint_each_wave` into `orch.submit(...)`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 3: HTTP Surface

**Files:**
- Modify: `tests/test_http_surface.py`
- Modify: `src/forum/http_surface.py`

**Interfaces:**
- Consumes: JSON field `checkpoint_each_wave`

- [ ] **Step 1: Write failing HTTP tests**

Add one test that submits with `"checkpoint_each_wave": true` and asserts checkpoint entries exist. Add one test that sends `"checkpoint_each_wave": "yes"` and expects status 400.

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_http_surface.py::test_submit_can_checkpoint_each_wave tests/test_http_surface.py::test_submit_rejects_non_boolean_checkpoint_each_wave -q
```

Expected: FAIL because the field is ignored and not validated.

- [ ] **Step 3: Implement HTTP parsing**

Read `checkpoint_each_wave = data.get("checkpoint_each_wave", False)`, require `bool`, and pass it to `self._orch.submit(...)`.

- [ ] **Step 4: Run green tests**

Run the same pytest command.

Expected: PASS.

---

### Task 4: MCP Surface

**Files:**
- Modify: `tests/test_mcp_surface.py`
- Modify: `src/forum/mcp_surface.py`

**Interfaces:**
- Consumes: `checkpoint_each_wave` tool argument for `submit` and `forum.submit`

- [ ] **Step 1: Write failing MCP test**

Call `forum.submit` with `{"request": "design an api", "checkpoint_each_wave": true}` and assert the underlying orchestrator ledger has checkpoint entries.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_mcp_surface.py::test_prefixed_submit_can_checkpoint_each_wave -q
```

Expected: FAIL because MCP does not forward the flag.

- [ ] **Step 3: Implement MCP schema and forwarding**

Add the property to `_SUBMIT_PROPERTIES` and forward it in `_submit_body` when present.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 5: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents high-level submit phase checkpoints.

- [ ] **Step 1: Update docs**

Mention `--checkpoint-each-wave` and HTTP/MCP parity in the run contract and command examples.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_engine.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_dispatch.py tests/test_report.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.
