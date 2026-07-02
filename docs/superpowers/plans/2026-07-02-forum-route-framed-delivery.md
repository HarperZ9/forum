# Forum Route-Framed Expert Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Forum submit runs inherit expert delivery profiles from deterministic route frames by default, with receipts showing the selected contract.

**Architecture:** `Orchestrator.submit` derives and witnesses a `forum.route-frame/v1` entry at request start. The route frame selects the default delivery profile unless the caller explicitly supplies one. Receipts read witnessed route-frame and delivery-profile entries so CLI, HTTP, and MCP submit surfaces expose what delivery contract shaped the run.

**Tech Stack:** Python 3.11, existing Forum ledger/route-frame/delivery-profile modules, stdlib JSON, pytest.

## Global Constraints

- No new runtime dependencies.
- Explicit `delivery_profile` keeps precedence over route-frame selection.
- Every normal submit run witnesses a `route_frame` entry.
- Every normal submit run gets a `delivery_profile_check` using either the explicit or route-frame-selected profile.
- Existing submit receipt fields stay compatible; new fields are additive.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `src/forum/engine.py`: derive route frame at submit start, witness it, select delivery profile source.
- Modify `src/forum/receipts.py`: include route frame and selected profile/source in submit receipts.
- Modify `tests/test_delivery.py`: engine-level route-frame delivery tests.
- Modify `tests/test_cli.py`, `tests/test_http_surface.py`, `tests/test_mcp_surface.py`: receipt surface tests.
- Modify `README.md`, `ARCHITECTURE.md`: document route-framed expert delivery.

---

### Task 1: Engine Route-Framed Delivery

**Files:**
- Modify: `src/forum/engine.py`
- Modify: `tests/test_delivery.py`

**Interfaces:**
- Consumes: `derive_route_frame(text, route_result)`, `frame_payload(frame)`, `get_profile(profile)`
- Produces: submit ledger entries with `kind="route_frame"` and automatic `delivery_profile_check`

- [ ] **Step 1: Write failing engine tests**

Add tests that submit a model-foundry request without explicit profile and assert the ledger contains a `route_frame` entry plus a `delivery_profile_check` for `engineer`; add a second test where explicit `delivery_profile="operator"` overrides the frame.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_delivery.py::test_submit_uses_route_frame_delivery_profile_by_default tests/test_delivery.py::test_explicit_delivery_profile_overrides_route_frame -q
```

Expected: FAIL because no `route_frame` entry exists and no profile check runs without explicit profile.

- [ ] **Step 3: Implement engine selection**

In `Orchestrator.submit`, derive the route frame after the request entry, witness it chained to the request, select `delivery_profile` from explicit input or frame, and pass the selected profile to `_witness_delivery_profile`.

- [ ] **Step 4: Verify engine tests pass**

Run the same targeted pytest command.

Expected: PASS.

---

### Task 2: Receipt Visibility

**Files:**
- Modify: `src/forum/receipts.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: route-frame ledger entries and delivery-profile ledger entries.
- Produces: submit receipt fields:
  - `route_frame`
  - `delivery_profile.requested`
  - `delivery_profile.selected`
  - `delivery_profile.source`

- [ ] **Step 1: Write failing receipt tests**

Add assertions to CLI, HTTP, and MCP submit tests that receipts include the witnessed route frame and selected delivery profile. Include one explicit override assertion in an existing delivery-profile submit test.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_cli.py::test_submit_json_returns_answer_and_receipt tests/test_http_surface.py::test_submit_answers_and_witnesses tests/test_mcp_surface.py::test_call_submit_answers_and_witnesses tests/test_http_surface.py::test_submit_accepts_delivery_profile_field -q
```

Expected: FAIL because receipt lacks route-frame and selected/source fields.

- [ ] **Step 3: Implement receipt readback**

Update `submit_receipt` to read route-frame and delivery-profile checks in the entries after `before_seq`. Set selected/source from observed profile checks and explicit request:
`explicit` when requested is not None; `route_frame` when selected came from route frame; `none` only when no check exists.

- [ ] **Step 4: Verify receipt tests pass**

Run the same targeted pytest command.

Expected: PASS.

---

### Task 3: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: route-framed submit behavior and receipt shape.
- Produces: documentation for automatic expert delivery profile selection.

- [ ] **Step 1: Update docs**

Document that route frames now choose the default expert delivery profile for submit runs and that receipts show the selection.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_delivery.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py tests/test_report.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `python -m pytest -q`

Expected: PASS.

- [ ] **Step 4: Manual receipt check**

Run:

```powershell
python -m forum submit "build eval gated model promotion for a daemon" --cmd "<test model command>" --json
```

Expected: receipt includes `route_frame.domain == "model-foundry"` and `delivery_profile.selected == "engineer"`.
