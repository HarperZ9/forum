# Forum Route Runtime Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose selected lane runtime policy (`model_tier`, `executor`) in route frames so local model surfaces can route work without rejoining roster data.

**Architecture:** Extend `RouteFrame` with optional runtime fields, let `derive_route_frame(..., roster=None)` join the decided agent to its `AgentSpec` when a roster is supplied, and pass the roster from production callers that already hold it. Existing route, submit, receipt, and run-room surfaces inherit the fields from the witnessed frame.

**Tech Stack:** Python 3.11, existing Forum routing/route-frame/HTTP/run-room modules and pytest.

## Global Constraints

- No new dependencies.
- Backwards-compatible `derive_route_frame(text, route)` call remains valid.
- Weak or escalated routes do not invent runtime policy.
- Route frame derivation remains local and deterministic.

---

## File Structure

- Modify `tests/test_route_frame.py`: pure runtime-policy expectations.
- Modify `tests/test_http_surface.py`: route endpoint includes runtime policy.
- Modify `tests/test_run_room.py`: witnessed submit route frame carries runtime policy.
- Modify `src/forum/route_frame.py`: add fields and roster join.
- Modify `src/forum/cli.py`, `src/forum/http_surface.py`, `src/forum/engine.py`: pass roster into frame derivation.
- Modify `README.md`, `ARCHITECTURE.md`: document the runtime policy contract.

---

### Task 1: Route-Frame Runtime Fields

**Files:**
- Modify: `tests/test_route_frame.py`
- Modify: `src/forum/route_frame.py`

- [ ] **Step 1: Write failing pure tests**

Assert a decided backend route exposes:

```python
assert frame.model_tier == "capable"
assert frame.executor == "cli"
```

Assert a weak route exposes `None` for both fields.

- [ ] **Step 2: Run red tests**

```powershell
python -m pytest tests/test_route_frame.py -q
```

Expected: FAIL because the fields do not exist.

- [ ] **Step 3: Implement fields and roster join**

Add optional fields to `RouteFrame`, add `roster=None` parameter to
`derive_route_frame`, and include the fields in `frame_payload`.

- [ ] **Step 4: Run green tests**

```powershell
python -m pytest tests/test_route_frame.py -q
```

Expected: PASS.

---

### Task 2: Surface Propagation

**Files:**
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_run_room.py`
- Modify: `src/forum/cli.py`
- Modify: `src/forum/http_surface.py`
- Modify: `src/forum/engine.py`

- [ ] **Step 1: Write failing surface tests**

Assert HTTP route response includes `frame.model_tier == "capable"` and
`frame.executor == "cli"`. Assert a submit run's room route frame includes the
same values.

- [ ] **Step 2: Run red tests**

```powershell
python -m pytest tests/test_http_surface.py::test_route_includes_runtime_policy tests/test_run_room.py::test_build_run_room_joins_current_run_state -q
```

Expected: FAIL because callers do not pass the roster yet.

- [ ] **Step 3: Pass roster through production callers**

Call `derive_route_frame(..., roster)` from CLI route, HTTP route, submit, and
assign.

- [ ] **Step 4: Run green surface tests**

```powershell
python -m pytest tests/test_http_surface.py::test_route_includes_runtime_policy tests/test_run_room.py::test_build_run_room_joins_current_run_state -q
```

Expected: PASS.

---

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Update docs**

Mention route-frame runtime policy as the contract local model endpoint routing
can consume.

- [ ] **Step 2: Run targeted tests**

```powershell
python -m pytest tests/test_route_frame.py tests/test_cli.py tests/test_http_surface.py tests/test_run_room.py tests/test_delivery.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```powershell
python -m pytest -q
```

Expected: PASS.
