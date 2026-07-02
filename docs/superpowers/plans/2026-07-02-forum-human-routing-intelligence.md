# Forum Human Routing Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic human route frames to Forum route outputs and route ledger entries.

**Architecture:** Add `forum.route_frame` as a zero-dependency module that derives a `RouteFrame` from request text and `RouteResult`. Public route surfaces keep existing fields and add a `frame` object, while `Orchestrator.assign` witnesses the same frame into route ledger payloads.

**Tech Stack:** Python 3.11, dataclasses, stdlib JSON, existing Forum CLI/HTTP/MCP surfaces, pytest.

## Global Constraints

- No new runtime dependencies.
- Existing route JSON fields stay compatible: `decided`, `confidence`, `needs_escalation`, and `candidates`.
- Frame schema is exactly `forum.route-frame/v1`.
- Frame derivation is deterministic local architecture, not model judgment.
- Unknown or weak routes return a general frame rather than raising.
- Tests are written and run before production code for each task.

---

## File Structure

- Create `src/forum/route_frame.py`: pure route-frame types, keyword signal matching, and JSON payload conversion.
- Create `tests/test_route_frame.py`: pure behavior tests for frame derivation.
- Modify `src/forum/cli.py`: `forum route` includes `frame`.
- Modify `src/forum/http_surface.py`: `POST /route` includes `frame`; MCP inherits this through `HttpSurface`.
- Modify `src/forum/engine.py`: `Orchestrator.assign` witnesses `frame` in route ledger entries.
- Modify `tests/test_cli.py`: CLI route output includes the frame.
- Modify `tests/test_http_surface.py`: HTTP route output includes the frame.
- Modify `tests/test_mcp_surface.py`: MCP route output includes the frame.
- Modify `tests/test_engine.py` or `tests/test_routing_ladder.py`: route ledger entries include the frame.
- Modify `README.md` and `ARCHITECTURE.md`: document route frames as deterministic routing posture contracts.

---

### Task 1: Pure Route Frame Module

**Files:**
- Create: `src/forum/route_frame.py`
- Create: `tests/test_route_frame.py`

**Interfaces:**
- Consumes: `forum.routing.RouteResult`
- Produces:
  - `ROUTE_FRAME_SCHEMA: str`
  - `RouteFrame` dataclass
  - `derive_route_frame(text: str, route: RouteResult) -> RouteFrame`
  - `frame_payload(frame: RouteFrame) -> dict`

- [ ] **Step 1: Write failing pure tests**

```python
from forum.roster import load_default
from forum.route_frame import ROUTE_FRAME_SCHEMA, derive_route_frame, frame_payload
from forum.routing import LexicalRouter


def _frame(text: str):
    route = LexicalRouter().score(text, load_default())
    return derive_route_frame(text, route)


def test_model_foundry_eval_work_gets_architect_frame():
    frame = _frame("build eval gated model promotion for a self improving daemon")
    assert frame.schema == ROUTE_FRAME_SCHEMA
    assert frame.agent == "model-foundry"
    assert frame.domain == "model-foundry"
    assert frame.intent == "validate"
    assert frame.posture == "architect"
    assert frame.delivery_profile == "engineer"
    assert frame.proof_lane == "validate"
    assert frame.domain_lane == "model-foundry"
    assert "eval" in frame.signals
    assert "gating evidence" in frame.human_contract


def test_evidence_work_gets_investigator_frame():
    frame = _frame("capture browser evidence from a source page with provenance")
    assert frame.domain == "evidence"
    assert frame.intent == "investigate"
    assert frame.posture == "investigator"
    assert frame.delivery_profile == "researcher"
    assert frame.proof_lane == "observe"
    assert frame.domain_lane == "source-federation"


def test_implementation_work_gets_execute_frame():
    frame = _frame("build the api database server endpoint")
    assert frame.agent == "backend"
    assert frame.domain == "implementation"
    assert frame.intent == "execute"
    assert frame.posture == "architect"
    assert frame.delivery_profile == "engineer"
    assert frame.proof_lane == "execute"


def test_weak_request_gets_general_operator_frame():
    frame = _frame("do the thing")
    assert frame.agent is None
    assert frame.domain == "general"
    assert frame.intent == "coordinate"
    assert frame.posture == "operator"
    assert frame.delivery_profile == "operator"
    assert frame.proof_lane is None
    assert frame.domain_lane is None


def test_frame_payload_is_json_ready():
    payload = frame_payload(_frame("teach the concept with an example"))
    assert payload["schema"] == ROUTE_FRAME_SCHEMA
    assert isinstance(payload["signals"], list)
```

- [ ] **Step 2: Verify tests fail**

Run: `python -m pytest tests/test_route_frame.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'forum.route_frame'`.

- [ ] **Step 3: Implement route frame module**

Create `src/forum/route_frame.py` with dataclasses, ordered keyword rules, token matching, safe defaults, and payload conversion.

- [ ] **Step 4: Verify pure tests pass**

Run: `python -m pytest tests/test_route_frame.py -q`

Expected: PASS.

---

### Task 2: Public Route Surfaces

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `src/forum/http_surface.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: `derive_route_frame(text, result)` and `frame_payload(frame)`
- Produces: route JSON with a `frame` object on CLI, HTTP, and MCP route calls.

- [ ] **Step 1: Write failing public-surface tests**

Add assertions that `forum route`, `POST /route`, and MCP `forum.route` return `frame.schema == "forum.route-frame/v1"` and expected posture/profile fields for representative requests.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_cli.py::test_route_includes_human_frame tests/test_http_surface.py::test_route_includes_human_frame tests/test_mcp_surface.py::test_prefixed_route_includes_human_frame -q
```

Expected: FAIL because `frame` is missing.

- [ ] **Step 3: Wire route surfaces**

Import `derive_route_frame` and `frame_payload` in CLI and HTTP route handlers. Add `"frame": frame_payload(derive_route_frame(text, result))` beside existing route fields.

- [ ] **Step 4: Verify route surface tests pass**

Run the same targeted pytest command.

Expected: PASS.

---

### Task 3: Route Ledger Witnessing

**Files:**
- Modify: `src/forum/engine.py`
- Modify: `tests/test_routing_ladder.py`

**Interfaces:**
- Consumes: `derive_route_frame` and `frame_payload`
- Produces: route ledger payloads with a `frame` object.

- [ ] **Step 1: Write failing ledger test**

Add a test that calls `Orchestrator.assign("build eval gated model promotion for a daemon")`, reads the `route` ledger entry, and asserts `payload["frame"]["posture"] == "architect"` and `payload["frame"]["delivery_profile"] == "engineer"`.

- [ ] **Step 2: Verify test fails**

Run: `python -m pytest tests/test_routing_ladder.py::test_assign_witnesses_route_frame -q`

Expected: FAIL because route payload has no `frame`.

- [ ] **Step 3: Wire `Orchestrator.assign`**

In `src/forum/engine.py`, derive the frame immediately after `routed = self.route(task)` and include the frame payload in the witnessed route entry.

- [ ] **Step 4: Verify ledger test passes**

Run: `python -m pytest tests/test_routing_ladder.py::test_assign_witnesses_route_frame -q`

Expected: PASS.

---

### Task 4: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: implemented route-frame schema and public output shape.
- Produces: documented behavior for deterministic human routing frames.

- [ ] **Step 1: Update docs**

Add concise documentation that Forum route outputs now carry a human route frame: domain, intent, posture, delivery profile, proof/domain lane hints, human contract, and signals.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_route_frame.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_routing_ladder.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Check route output manually**

Run:

```powershell
python -m forum route --json "build eval gated model promotion for a self improving daemon"
python -m forum route --json "capture browser evidence from a source page with provenance"
```

Expected: both outputs include `frame.schema` equal to `forum.route-frame/v1` and posture/profile fields matching the request type.
