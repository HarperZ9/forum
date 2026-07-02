# Forum Run Room Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only run-room snapshot that projects the latest run's ledger state into one operator-facing payload.

**Architecture:** Create a pure `forum.run_room` module that reads `Ledger` entries and payloads, defaults to the latest request, clips long text, and joins tasks with latest result/verdict/checkpoint/answer/signals. Expose it through CLI, HTTP, and MCP inspection surfaces.

**Tech Stack:** Python 3.11, existing Forum ledger/storage/surface modules, pytest.

## Global Constraints

- No new runtime dependencies.
- Run room generation is read-only and appends no ledger entries.
- Full raw text stays in the ledger; room payload text fields are clipped.
- Default room scope is the latest request lineage.
- Tests are written and run before production code for each task.

---

## File Structure

- Create `src/forum/run_room.py`: pure room builder and text renderer.
- Create `tests/test_run_room.py`: pure room behavior tests.
- Modify `src/forum/cli.py`, `tests/test_cli.py`: `forum ledger room`.
- Modify `src/forum/http_surface.py`, `tests/test_http_surface.py`: `GET /room`.
- Modify `src/forum/mcp_surface.py`, `tests/test_mcp_surface.py`: `forum.run.room`.
- Modify `README.md`, `ARCHITECTURE.md`: document run rooms.

---

### Task 1: Pure Run Room Builder

**Files:**
- Create: `src/forum/run_room.py`
- Create: `tests/test_run_room.py`

**Interfaces:**
- Produces: `RUN_ROOM_SCHEMA = "forum.run-room/v1"`
- Produces: `build_run_room(ledger, since_seq: int | None = None, max_text_chars: int = 240) -> dict`
- Produces: `room_text(room: dict) -> str`

- [ ] **Step 1: Write failing pure tests**

Add tests that seed a ledger with request, route frame, plan, task with `done_when`, result, verdict, checkpoint, answer, delivery profile check, and context budget. Assert the room payload contains clipped request/answer, plan waves, task contract/result/verdict, checkpoints, route frame, signals, checkpoint root, and verification. Add a second test proving latest-request filtering ignores an earlier run.

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_run_room.py -q
```

Expected: FAIL because `forum.run_room` does not exist.

- [ ] **Step 3: Implement pure module**

Implement clipping, latest request selection, payload loading, task/result/verdict joins, signal counts, and text rendering.

- [ ] **Step 4: Run green tests**

Run the same pytest command.

Expected: PASS.

---

### Task 2: CLI Surface

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Produces: `forum ledger room --json`

- [ ] **Step 1: Write failing CLI test**

Seed a ledger, call `main(["ledger", "room", "--ledger", str(path), "--json"])`, parse stdout, and assert `schema == "forum.run-room/v1"`.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_cli.py::test_ledger_room_json -q
```

Expected: FAIL because `room` subcommand is missing.

- [ ] **Step 3: Implement CLI command**

Add `_cmd_ledger_room`, wire `ledger room`, support `--json`, `--text`, and `--max-text-chars`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 3: HTTP Surface

**Files:**
- Modify: `src/forum/http_surface.py`
- Modify: `tests/test_http_surface.py`

**Interfaces:**
- Produces: `GET /room`

- [ ] **Step 1: Write failing HTTP test**

After a submit call, call `GET /room` and assert the payload schema and latest answer.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_http_surface.py::test_room_returns_run_room_snapshot -q
```

Expected: FAIL with 404.

- [ ] **Step 3: Implement HTTP route**

Add `/room` to known paths and return `build_run_room(self._orch.ledger)`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 4: MCP Surface

**Files:**
- Modify: `src/forum/mcp_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Produces: MCP tool `forum.run.room`

- [ ] **Step 1: Write failing MCP test**

Submit through MCP, then call `forum.run.room` and assert room schema and answer.

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_mcp_surface.py::test_call_prefixed_run_room_after_submit -q
```

Expected: FAIL because the MCP tool does not exist.

- [ ] **Step 3: Implement MCP route and tool spec**

Map `forum.run.room` to `GET /room` and add it to `_TOOL_SPECS`.

- [ ] **Step 4: Run green test**

Run the same pytest command.

Expected: PASS.

---

### Task 5: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents run rooms as the operator/platform read model.

- [ ] **Step 1: Update docs**

Mention `forum ledger room --json`, `GET /room`, and MCP `forum.run.room`.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_run_room.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_context_capsule.py tests/test_report.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.
