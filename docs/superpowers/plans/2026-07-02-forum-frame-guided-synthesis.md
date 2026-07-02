# Forum Frame-Guided Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pass the route-frame human contract into final-answer synthesis before the delivery-profile check runs.

**Architecture:** Extend `Synthesizer.synthesize` with an optional `delivery_contract` string. `Orchestrator.submit` builds that string from the witnessed route frame and selected delivery profile, then passes it into synthesis. The route frame remains the witnessed contract source.

**Tech Stack:** Python 3.11, existing Forum control loop, route-frame module, pytest.

## Global Constraints

- No new runtime dependencies.
- Existing `Synthesizer.synthesize(request, results, executor)` calls remain valid.
- The guidance is advisory prompt input; the trusted evidence remains the witnessed route frame and delivery-profile check.
- Do not imitate named writers or living people.
- Tests are written and run before production code for each task.

---

## File Structure

- Modify `src/forum/control.py`: optional delivery contract in synthesizer prompt.
- Modify `src/forum/engine.py`: build route-frame-derived contract and pass it into synthesis.
- Modify `tests/test_synthesizer.py`: direct synthesizer prompt tests.
- Modify `tests/test_delivery.py`: submit-level prompt guidance test.
- Modify `README.md`, `ARCHITECTURE.md`: document frame-guided synthesis.

---

### Task 1: Synthesizer Contract Prompt

**Files:**
- Modify: `src/forum/control.py`
- Modify: `tests/test_synthesizer.py`

**Interfaces:**
- Produces: `Synthesizer.synthesize(request, results, executor, delivery_contract: str = "") -> str`

- [ ] **Step 1: Write failing synthesizer tests**

Add a capturing executor test that calls `Synthesizer().synthesize(..., delivery_contract="Answer as an architect.")` and asserts the prompt contains `Delivery contract:` and the contract text. Add a no-contract test that asserts the prompt does not contain `Delivery contract:`.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_synthesizer.py::test_synthesizer_includes_delivery_contract_when_provided tests/test_synthesizer.py::test_synthesizer_omits_delivery_contract_by_default -q
```

Expected: FAIL because `delivery_contract` is not accepted.

- [ ] **Step 3: Implement optional prompt block**

Update `Synthesizer.synthesize` signature and prompt construction. Insert:

```text
Delivery contract:
<contract>
```

before `Write the final answer.` only when the contract is non-empty after stripping.

- [ ] **Step 4: Verify synthesizer tests pass**

Run the same targeted pytest command.

Expected: PASS.

---

### Task 2: Submit Uses Route-Frame Guidance

**Files:**
- Modify: `src/forum/engine.py`
- Modify: `tests/test_delivery.py`

**Interfaces:**
- Consumes: route frame fields `posture`, `delivery_profile`, `domain`, `intent`, `human_contract`
- Produces: route-frame-derived delivery contract passed into final synthesis.

- [ ] **Step 1: Write failing submit prompt test**

Add a scripted executor that records the synthesizer prompt during `Orchestrator.submit("build eval gated model promotion for a daemon")`. Assert it contains `Delivery contract:`, `posture=architect`, `profile=engineer`, `domain=model-foundry`, and the route frame human contract text.

- [ ] **Step 2: Verify test fails**

Run:

```powershell
python -m pytest tests/test_delivery.py::test_submit_passes_route_frame_contract_to_synthesizer -q
```

Expected: FAIL because the synthesizer prompt lacks the delivery contract block.

- [ ] **Step 3: Implement route-frame contract builder**

In `engine.py`, add a small private helper to format the route frame and selected profile into a compact contract string. Pass it to `self.synthesizer.synthesize(..., delivery_contract=contract)`.

- [ ] **Step 4: Verify submit prompt test passes**

Run the same targeted pytest command.

Expected: PASS.

---

### Task 3: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents frame-guided synthesis as local prompt guidance plus witnessed profile check.

- [ ] **Step 1: Update docs**

Explain that the route frame now guides the synthesis prompt before the answer is generated.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
python -m pytest tests/test_synthesizer.py tests/test_delivery.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `python -m pytest -q`

Expected: PASS.
