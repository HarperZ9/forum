# Forum Context Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `forum context preflight` command that estimates request and optional capsule context pressure before submit.

**Architecture:** Create a focused `context_preflight` module over the existing `ContextBudget`, `ContextBudgetMeter`, `apply_context_budget`, and `approx_tokens` functions. The CLI builds optional capsule context from the ledger, constructs the same budget object as submit, and prints JSON or text without writing ledger entries.

**Tech Stack:** Python 3.11, argparse, existing Forum ledger/capsule/context budget modules, pytest, Ruff.

## Global Constraints

- No model calls.
- No provider-specific tokenizers.
- No ledger mutation.
- JSON must not include raw capsule context text.
- Use the same approximate-token rule and `ContextBudget` behavior as submit.

---

### Task 1: Context Preflight Module

**Files:**
- Create: `src/forum/context_preflight.py`
- Test: `tests/test_context_preflight.py`

**Interfaces:**
- Produces: `build_context_preflight(request: str, context: str = "", context_source: str = "none", budget: ContextBudget | None = None) -> dict`
- Produces: `context_preflight_text(payload: dict) -> str`

- [ ] **Step 1: Write failing tests**

Add tests for request token counting, trimmed context with a request-context limit, and omitted context when total budget is zero.

- [ ] **Step 2: Run red**

Run: `pytest tests/test_context_preflight.py -q`
Expected: FAIL because `forum.context_preflight` does not exist.

- [ ] **Step 3: Implement module**

Use `approx_tokens` for request counts and `apply_context_budget("request", ...)` when context and budget are present. Emit schema, ready, request counts, context counts, limits, and issues.

- [ ] **Step 4: Run green**

Run: `pytest tests/test_context_preflight.py -q`
Expected: PASS.

### Task 2: CLI Surface

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: `_make_context_budget(args)`
- Produces: `forum context preflight TEXT [--use-capsule-context] [budget flags] [--json]`

- [ ] **Step 1: Write failing CLI tests**

Add tests for JSON and text output. Seed a ledger for capsule preflight.

- [ ] **Step 2: Run red**

Run: `pytest tests/test_cli.py::test_context_preflight_json tests/test_cli.py::test_context_preflight_text -q`
Expected: FAIL because `context` subcommand does not exist.

- [ ] **Step 3: Implement CLI**

Add `_add_context_budget`, reuse it for submit and context preflight, add `context preflight` parser, and make invalid budget return exit code `2`.

- [ ] **Step 4: Run targeted verification**

Run: `pytest tests/test_context_preflight.py tests/test_cli.py -q`
Expected: PASS.

### Task 3: Final Verification

**Files:**
- All changed files

- [ ] **Step 1: Run Ruff**

Run: `python -m ruff check src/forum/context_preflight.py src/forum/cli.py tests/test_context_preflight.py tests/test_cli.py`
Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

Run staged whitespace and focused secret checks, then commit with:

```bash
git commit -m "feat: add context preflight surface"
```

## Self-Review

- Spec coverage: request estimate, optional capsule, budget application, JSON/text CLI, and docs are covered.
- Placeholder scan: no TBD/TODO/fill-in sections.
- Type consistency: `build_context_preflight` and `context_preflight_text` are used consistently across module and CLI tasks.
