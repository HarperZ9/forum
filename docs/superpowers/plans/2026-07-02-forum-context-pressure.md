# Forum Context Pressure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, witnessed context/token pressure controls to Forum so request context, per-task context, and upstream data injection are admitted, trimmed, or omitted under explicit budgets.

**Architecture:** Add a pure `forum.context_budget` module for UTF-8 byte and approximate-token accounting, then wire it into the existing `Orchestrator.submit`, `dispatch_plan`, reports, receipts, and CLI/HTTP/MCP surfaces. Index remains the peer context producer; Forum enforces and witnesses the budget decisions without importing Index.

**Tech Stack:** Python 3.11+, standard library only, existing Forum ledger/storage/orchestrator stack, pytest for tests, argparse for CLI, stdlib JSON HTTP/MCP surfaces.

## Global Constraints

- Forum core stays zero-dependency.
- Budgeting is deterministic and replayable.
- Context accounting is model-agnostic and compatible with Index's documented `bytes_per_token = 4` approximation.
- Budget decisions never silently drop material; they retain, trim, or omit with a ledger reason.
- No `ContextBudget` preserves existing behavior except new report fields defaulting to zero.
- CLI, HTTP, MCP, Python API, README, USAGE, ARCHITECTURE, and CHANGELOG stay aligned.
- Tests cover core budgeting, dispatch integration, orchestrator integration, summary metrics, and surface parsing.

---

## Platform Direction and OpenClacky Benchmark

OpenClacky is the near-term public harness benchmark to exceed: token efficiency,
BYOK/OpenAI-compatible model freedom, compact tool surface, skill evolution,
multi-session web UI, plugin/skill extension work, IM integrations, and multimedia model
support. Forum's target is broader than harness parity. It should become the Project
Telos user platform and execution layer: run rooms, receipts, context admission,
advanced local model endpoints, research-driven task routing, artifact/media lanes, and
expert-grade delivery profiles.

This plan keeps v1.13 focused on Context Pressure because every later platform feature
needs a witnessed context contract. Do not turn this implementation into a web UI,
plugin marketplace, or local-model runtime. Add docs that name those as downstream
platform milestones once context pressure is measurable.

---

## File Structure

- Create `src/forum/context_budget.py`: pure dataclasses and functions for approximate-token accounting, budget admission, pressure payloads, and observed metrics.
- Create `tests/test_context_budget.py`: unit tests for accounting, validation, retained/trimmed/omitted decisions, and total budget consumption.
- Modify `src/forum/engine.py`: accept `context_budget` in `submit`, apply it before request-level context reaches the coordinator, witness pressure entries, and pass the same budget/meter into dispatch.
- Modify `src/forum/dispatch.py`: add budget-aware upstream injection and per-task context admission while preserving current no-budget behavior.
- Modify `tests/test_context.py` and `tests/test_dispatch.py`: cover request-level, per-task, and upstream budget behavior.
- Modify `src/forum/report.py` and `tests/test_report.py`: summarize context pressure metrics and include them in bench deltas.
- Modify `src/forum/receipts.py`: include compact context-budget limits and observed metrics in submit receipts.
- Modify `src/forum/cli.py`, `src/forum/http_surface.py`, and `src/forum/mcp_surface.py`: parse/pass context budget controls across all public surfaces.
- Modify `tests/test_cli.py`, `tests/test_http_surface.py`, and `tests/test_mcp_surface.py`: cover surface parsing and parity.
- Modify `README.md`, `USAGE.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, and add `examples/run_context_pressure.py`: document the new workflow and runnable example.
- Keep downstream platform direction visible in docs: Forum should exceed harnesses like OpenClacky by combining context pressure, receipts, platform execution, advanced local model endpoints, and expert delivery profiles.

---

### Task 1: Pure Context Budget Core

**Files:**
- Create: `src/forum/context_budget.py`
- Create: `tests/test_context_budget.py`

**Interfaces:**
- Produces: `ContextBudget`, `ContextPressure`, `ContextBudgetMeter`, `approx_tokens`, `apply_context_budget`, `pressure_payload`, `observed_context_budget`.
- Consumes: only Python stdlib.

- [ ] **Step 1: Write failing tests for byte/token accounting and validation**

Create `tests/test_context_budget.py` with:

```python
import pytest

from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    apply_context_budget,
    approx_tokens,
    observed_context_budget,
    pressure_payload,
)


def test_approx_tokens_uses_utf8_bytes_and_ceil():
    assert approx_tokens("") == 0
    assert approx_tokens("abcd") == 1
    assert approx_tokens("abcde") == 2
    assert approx_tokens("字") == 1
    assert approx_tokens("字字") == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_total_tokens": -1},
        {"max_request_tokens": -1},
        {"max_task_tokens": -1},
        {"max_upstream_tokens": -1},
        {"bytes_per_token": 0},
    ],
)
def test_context_budget_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        ContextBudget(**kwargs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_context_budget.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'forum.context_budget'`.

- [ ] **Step 3: Add the core module**

Create `src/forum/context_budget.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = "forum.context-pressure/v1"
DEFAULT_BYTES_PER_TOKEN = 4

SOURCES = frozenset({"request", "task", "upstream"})
REASONS = frozenset({
    "under_budget",
    "max_request_tokens",
    "max_task_tokens",
    "max_upstream_tokens",
    "max_total_tokens",
    "empty",
})


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_total_tokens: int | None = None
    max_request_tokens: int | None = None
    max_task_tokens: int | None = None
    max_upstream_tokens: int | None = None
    bytes_per_token: int = DEFAULT_BYTES_PER_TOKEN

    def __post_init__(self) -> None:
        for name in (
            "max_total_tokens",
            "max_request_tokens",
            "max_task_tokens",
            "max_upstream_tokens",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be > 0")

    def limit_for(self, source: str) -> int | None:
        if source == "request":
            return self.max_request_tokens
        if source == "task":
            return self.max_task_tokens
        if source == "upstream":
            return self.max_upstream_tokens
        raise ValueError(f"unknown context source: {source}")

    def configured_limits(self) -> dict[str, int]:
        out: dict[str, int] = {"bytes_per_token": self.bytes_per_token}
        for key in (
            "max_total_tokens",
            "max_request_tokens",
            "max_task_tokens",
            "max_upstream_tokens",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True, slots=True)
class ContextPressure:
    source: str
    label: str
    original_bytes: int
    admitted_bytes: int
    original_tokens: int
    admitted_tokens: int
    action: str
    reason: str


@dataclass(slots=True)
class ContextBudgetMeter:
    admitted_tokens_total: int = 0
    pressures: list[ContextPressure] = field(default_factory=list)

    def remaining_total(self, budget: ContextBudget) -> int | None:
        if budget.max_total_tokens is None:
            return None
        return max(0, budget.max_total_tokens - self.admitted_tokens_total)

    def record(self, pressure: ContextPressure) -> None:
        self.admitted_tokens_total += pressure.admitted_tokens
        self.pressures.append(pressure)


def approx_tokens(text: str, bytes_per_token: int = DEFAULT_BYTES_PER_TOKEN) -> int:
    if bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be > 0")
    n = len(text.encode("utf-8"))
    if n == 0:
        return 0
    return (n + bytes_per_token - 1) // bytes_per_token


def _slice_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _effective_limit(source: str, budget: ContextBudget, meter: ContextBudgetMeter) -> tuple[int | None, str]:
    source_limit = budget.limit_for(source)
    total_remaining = meter.remaining_total(budget)
    if source_limit is None and total_remaining is None:
        return None, "under_budget"
    if source_limit is None:
        return total_remaining, "max_total_tokens"
    if total_remaining is None:
        return source_limit, f"max_{source}_tokens"
    if total_remaining <= source_limit:
        return total_remaining, "max_total_tokens"
    return source_limit, f"max_{source}_tokens"


def apply_context_budget(
    source: str,
    label: str,
    text: str,
    budget: ContextBudget,
    meter: ContextBudgetMeter,
) -> tuple[str, ContextPressure]:
    if source not in SOURCES:
        raise ValueError(f"unknown context source: {source}")
    original_bytes = len(text.encode("utf-8"))
    original_tokens = approx_tokens(text, budget.bytes_per_token)
    if original_tokens == 0:
        pressure = ContextPressure(source, label, original_bytes, 0, 0, 0, "retained", "empty")
        meter.record(pressure)
        return "", pressure

    limit, reason = _effective_limit(source, budget, meter)
    if limit is None or original_tokens <= limit:
        pressure = ContextPressure(
            source, label, original_bytes, original_bytes,
            original_tokens, original_tokens, "retained", "under_budget",
        )
        meter.record(pressure)
        return text, pressure
    if limit <= 0:
        pressure = ContextPressure(
            source, label, original_bytes, 0,
            original_tokens, 0, "omitted", reason,
        )
        meter.record(pressure)
        return "", pressure

    admitted = _slice_utf8(text, limit * budget.bytes_per_token)
    admitted_bytes = len(admitted.encode("utf-8"))
    admitted_tokens = approx_tokens(admitted, budget.bytes_per_token)
    pressure = ContextPressure(
        source, label, original_bytes, admitted_bytes,
        original_tokens, admitted_tokens, "trimmed", reason,
    )
    meter.record(pressure)
    return admitted, pressure


def pressure_payload(
    pressure: ContextPressure,
    budget: ContextBudget,
    meter: ContextBudgetMeter,
) -> dict:
    return {
        "schema": SCHEMA,
        "source": pressure.source,
        "label": pressure.label,
        "action": pressure.action,
        "reason": pressure.reason,
        "original_bytes": pressure.original_bytes,
        "admitted_bytes": pressure.admitted_bytes,
        "original_tokens": pressure.original_tokens,
        "admitted_tokens": pressure.admitted_tokens,
        "remaining_total_tokens": meter.remaining_total(budget),
    }


def observed_context_budget(pressures: list[ContextPressure]) -> dict:
    original = sum(p.original_tokens for p in pressures)
    admitted = sum(p.admitted_tokens for p in pressures)
    return {
        "checks": len(pressures),
        "trimmed": sum(1 for p in pressures if p.action == "trimmed"),
        "omitted": sum(1 for p in pressures if p.action == "omitted"),
        "tokens_original": original,
        "tokens_admitted": admitted,
        "tokens_saved": original - admitted,
    }
```

- [ ] **Step 4: Add tests for retained, trimmed, omitted, and observed metrics**

Append to `tests/test_context_budget.py`:

```python
def test_context_under_budget_is_retained():
    budget = ContextBudget(max_task_tokens=10)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("task", "T1", "small context", budget, meter)
    assert admitted == "small context"
    assert pressure.action == "retained"
    assert pressure.reason == "under_budget"
    assert meter.admitted_tokens_total == pressure.admitted_tokens


def test_context_over_source_limit_is_trimmed():
    budget = ContextBudget(max_task_tokens=2)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("task", "T1", "abcdefghijklmnop", budget, meter)
    assert admitted == "abcdefgh"
    assert pressure.action == "trimmed"
    assert pressure.reason == "max_task_tokens"
    assert pressure.original_tokens == 4
    assert pressure.admitted_tokens == 2


def test_total_budget_can_omit_later_context():
    budget = ContextBudget(max_total_tokens=2)
    meter = ContextBudgetMeter()
    first, first_pressure = apply_context_budget("request", "request", "abcdefgh", budget, meter)
    second, second_pressure = apply_context_budget("task", "T1", "abcd", budget, meter)
    assert first == "abcdefgh"
    assert first_pressure.action == "retained"
    assert second == ""
    assert second_pressure.action == "omitted"
    assert second_pressure.reason == "max_total_tokens"


def test_pressure_payload_and_observed_summary():
    budget = ContextBudget(max_total_tokens=2)
    meter = ContextBudgetMeter()
    apply_context_budget("request", "request", "abcdefgh", budget, meter)
    _, pressure = apply_context_budget("task", "T1", "abcd", budget, meter)
    payload = pressure_payload(pressure, budget, meter)
    assert payload["schema"] == "forum.context-pressure/v1"
    assert payload["remaining_total_tokens"] == 0
    observed = observed_context_budget(meter.pressures)
    assert observed == {
        "checks": 2,
        "trimmed": 0,
        "omitted": 1,
        "tokens_original": 3,
        "tokens_admitted": 2,
        "tokens_saved": 1,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_context_budget.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/forum/context_budget.py tests/test_context_budget.py
git commit -m "feat: add context pressure budget core"
```

---

### Task 2: Request-Level Context Budgeting in the Orchestrator

**Files:**
- Modify: `src/forum/engine.py`
- Modify: `tests/test_context.py`

**Interfaces:**
- Consumes: `ContextBudget`, `ContextBudgetMeter`, `apply_context_budget`, `pressure_payload` from Task 1.
- Produces: `Orchestrator.submit(request, *, budget=None, context_budget=None)` and request-level `context_budget` ledger entries.

- [ ] **Step 1: Write failing request-level context tests**

Append to `tests/test_context.py`:

```python
def test_request_context_budget_trims_before_planning():
    from forum.context_budget import ContextBudget

    class _BigCtx:
        def context(self, request):
            return "abcdefghij" * 10

    rec = _Recorder()
    led, orch = _orch(rec, provider=_BigCtx())
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_request_tokens=2)))

    budget_entries = led.query(kind="context_budget")
    assert len(budget_entries) >= 1
    budget_body = led.get_payload(budget_entries[0].payload_hash)
    assert budget_body["schema"] == "forum.context-pressure/v1"
    assert budget_body["source"] == "request"
    assert budget_body["action"] == "trimmed"
    assert budget_body["reason"] == "max_request_tokens"

    request_ctx = next(e for e in led.query(kind="context") if "task" not in led.get_payload(e.payload_hash))
    ctx = led.get_payload(request_ctx.payload_hash)["context"]
    assert ctx == "abcdefgh"
    assert "abcdefgh" in rec.prompts["coordinator"]
    assert "abcdefghijabcdefghij" not in rec.prompts["coordinator"]
    assert led.verify(deep=True) is True


def test_request_context_budget_can_omit_context_and_keep_planning():
    from forum.context_budget import ContextBudget

    class _Ctx:
        def context(self, request):
            return "context"

    rec = _Recorder()
    led, orch = _orch(rec, provider=_Ctx())
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_total_tokens=0)))

    bodies = [led.get_payload(e.payload_hash) for e in led.query(kind="context_budget")]
    assert bodies[0]["source"] == "request"
    assert bodies[0]["action"] == "omitted"
    assert bodies[0]["reason"] == "max_total_tokens"
    assert "Context (organized knowledge to use)" not in rec.prompts["coordinator"]
    assert led.verify(deep=True) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_context.py::test_request_context_budget_trims_before_planning tests/test_context.py::test_request_context_budget_can_omit_context_and_keep_planning -q
```

Expected: FAIL with `TypeError: Orchestrator.submit() got an unexpected keyword argument 'context_budget'`.

- [ ] **Step 3: Import budget helpers and update the submit signature**

In `src/forum/engine.py`, add imports:

```python
from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    apply_context_budget,
    pressure_payload,
)
```

Change:

```python
async def submit(self, request: str, *, budget: RunBudget | None = None) -> str:
```

to:

```python
async def submit(
    self,
    request: str,
    *,
    budget: RunBudget | None = None,
    context_budget: ContextBudget | None = None,
) -> str:
```

- [ ] **Step 4: Apply and witness request-level context pressure**

Inside `submit`, after `start = time.monotonic()`, add:

```python
context_meter = ContextBudgetMeter()
```

Replace:

```python
context = self.context_provider.context(request)
parent = req.seq
if context:
    parent = self.ledger.append(
        actor="context", kind="context", payload={"context": context}, causal_parent=req.seq
    ).seq
```

with:

```python
context = self.context_provider.context(request)
parent = req.seq
if context_budget is not None:
    context, pressure = apply_context_budget("request", "request", context, context_budget, context_meter)
    if pressure.original_tokens > 0:
        self.ledger.append(
            actor="context-budget",
            kind="context_budget",
            payload=pressure_payload(pressure, context_budget, context_meter),
            causal_parent=req.seq,
        )
if context:
    parent = self.ledger.append(
        actor="context", kind="context", payload={"context": context}, causal_parent=req.seq
    ).seq
```

- [ ] **Step 5: Pass the same budget and meter to dispatch**

In the `dispatch_plan` call inside `submit`, add:

```python
context_budget=context_budget,
context_meter=context_meter,
```

The call block should include:

```python
results = await dispatch_plan(
    plan, self.ledger, counter,
    max_parallel=self.policy.max_parallel, parent_seq=parent, over_budget=over_budget,
    context_provider=self.context_provider,
    context_budget=context_budget,
    context_meter=context_meter,
)
```

This step will still fail until Task 3 updates `dispatch_plan`.

- [ ] **Step 6: Run request-level tests after Task 3 is complete**

Run:

```bash
python -m pytest tests/test_context.py::test_request_context_budget_trims_before_planning tests/test_context.py::test_request_context_budget_can_omit_context_and_keep_planning -q
```

Expected after Task 3: PASS.

- [ ] **Step 7: Commit after Task 3 passes**

Commit this task together with Task 3, because `engine.py` depends on the new `dispatch_plan` parameters:

```bash
git add src/forum/engine.py tests/test_context.py
git commit -m "feat: budget request context pressure"
```

---

### Task 3: Dispatch Per-Task and Upstream Context Budgeting

**Files:**
- Modify: `src/forum/dispatch.py`
- Modify: `tests/test_dispatch.py`

**Interfaces:**
- Consumes: `ContextBudget`, `ContextBudgetMeter`, `apply_context_budget`, `pressure_payload` from Task 1.
- Produces: `dispatch_plan(plan, ledger, executor, *, context_budget=None, context_meter=None)` and `augment_with_upstream_budgeted`.

- [ ] **Step 1: Write failing dispatch tests**

Append to `tests/test_dispatch.py`:

```python
def test_per_task_context_budget_trims_and_witnesses_pressure():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()

    class _Big:
        def context(self, text):
            return "abcdefghijklmnop"

    plan = Plan((Task("T1", "x", "go", ()),))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _EchoSawExecutor(),
            context_provider=_Big(),
            context_budget=ContextBudget(max_task_tokens=2),
        )
    )
    assert "Context for this task:" in results["T1"].output
    assert "abcdefgh" in results["T1"].output
    assert "abcdefghijklmnop" not in results["T1"].output
    bodies = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context_budget")]
    assert any(b["source"] == "task" and b["action"] == "trimmed" for b in bodies)
    assert ledger.verify(deep=True) is True


def test_per_task_context_budget_omits_context_when_total_is_spent():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()

    class _Big:
        def context(self, text):
            return "abcd"

    plan = Plan((Task("T1", "x", "go", ()),))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _EchoSawExecutor(),
            context_provider=_Big(),
            context_budget=ContextBudget(max_total_tokens=0),
        )
    )
    assert "Context for this task:" not in results["T1"].output
    budget_body = ledger.get_payload(ledger.query(kind="context_budget")[0].payload_hash)
    assert budget_body["source"] == "task"
    assert budget_body["action"] == "omitted"
    assert budget_body["reason"] == "max_total_tokens"
    assert ledger.get(_task_entry(ledger, "T1").causal_parent).kind == "plan"
    assert ledger.verify(deep=True) is True


def test_upstream_context_budget_trims_prompt_but_keeps_full_result():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _BigT1(),
            max_parallel=2,
            context_budget=ContextBudget(max_upstream_tokens=2),
        )
    )
    assert "truncated for prompt efficiency" in results["T2"].output
    assert "x" * 8 in results["T2"].output
    assert "x" * 10000 not in results["T2"].output
    budget_bodies = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context_budget")]
    assert any(b["source"] == "upstream" and b["label"] == "T1->T2" for b in budget_bodies)
    t1_result = next(
        ledger.get_payload(e.payload_hash)
        for e in ledger.query(kind="result")
        if ledger.get_payload(e.payload_hash).get("id") == "T1"
    )
    assert t1_result["output"] == "x" * 10000
```

- [ ] **Step 2: Run dispatch tests to verify they fail**

Run:

```bash
python -m pytest tests/test_dispatch.py::test_per_task_context_budget_trims_and_witnesses_pressure tests/test_dispatch.py::test_per_task_context_budget_omits_context_when_total_is_spent tests/test_dispatch.py::test_upstream_context_budget_trims_prompt_but_keeps_full_result -q
```

Expected: FAIL with `TypeError: dispatch_plan() got an unexpected keyword argument 'context_budget'`.

- [ ] **Step 3: Import context budget helpers**

At the top of `src/forum/dispatch.py`, add:

```python
from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    ContextPressure,
    apply_context_budget,
    pressure_payload,
)
```

- [ ] **Step 4: Add a budget-aware upstream helper**

After `augment_with_upstream`, add:

```python
def augment_with_upstream_budgeted(
    task: Task,
    results: dict[str, Result],
    *,
    context_budget: ContextBudget,
    context_meter: ContextBudgetMeter,
) -> tuple[str, list[str], list[ContextPressure]]:
    parts: list[str] = []
    data_from: list[str] = []
    pressures: list[ContextPressure] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is None or not up.ok or dep in data_from:
            continue
        output, pressure = apply_context_budget(
            "upstream", f"{dep}->{task.id}", up.output, context_budget, context_meter
        )
        pressures.append(pressure)
        if not output:
            continue
        if pressure.action == "trimmed":
            omitted = pressure.original_bytes - pressure.admitted_bytes
            output = output + f"\n... [truncated for prompt efficiency, {omitted} bytes omitted; full output is witnessed]"
        parts.append(f"- {dep}: {output}")
        data_from.append(dep)
    if not parts:
        return task.instruction, [], pressures
    return task.instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from, pressures
```

- [ ] **Step 5: Update `dispatch_plan` signature**

Change the signature to include:

```python
context_budget: ContextBudget | None = None,
context_meter: ContextBudgetMeter | None = None,
```

The full tail of the parameter list should be:

```python
max_upstream_chars: int = DEFAULT_MAX_UPSTREAM_CHARS,
context_provider: ContextProvider | None = None,
context_budget: ContextBudget | None = None,
context_meter: ContextBudgetMeter | None = None,
) -> dict[str, Result]:
```

At the start of `dispatch_plan`, after `results: dict[str, Result] = {}`, add:

```python
if context_budget is not None and context_meter is None:
    context_meter = ContextBudgetMeter()
```

- [ ] **Step 6: Witness upstream budget pressures**

Replace:

```python
instruction, data_from = augment_with_upstream(task, results, max_chars=max_upstream_chars)
```

with:

```python
if context_budget is not None and context_meter is not None:
    instruction, data_from, upstream_pressures = augment_with_upstream_budgeted(
        task, results, context_budget=context_budget, context_meter=context_meter
    )
    for pressure in upstream_pressures:
        ledger.append(
            actor="context-budget",
            kind="context_budget",
            payload=pressure_payload(pressure, context_budget, context_meter),
            causal_parent=plan_entry.seq,
        )
else:
    instruction, data_from = augment_with_upstream(task, results, max_chars=max_upstream_chars)
```

- [ ] **Step 7: Budget and witness per-task context**

Replace the current per-task context block:

```python
ctx = context_provider.context(task.instruction)
if ctx:
    if len(ctx) > max_upstream_chars:
        ctx = ctx[:max_upstream_chars] + "\n... [truncated for prompt efficiency]"
    task_parent = ledger.append(
        actor="context", kind="context",
        payload={"task": task.id, "context": ctx}, causal_parent=plan_entry.seq,
    ).seq
    instruction = instruction + "\n\nContext for this task:\n" + ctx
```

with:

```python
ctx = context_provider.context(task.instruction)
if context_budget is not None and context_meter is not None:
    ctx, pressure = apply_context_budget("task", task.id, ctx, context_budget, context_meter)
    if pressure.original_tokens > 0:
        ledger.append(
            actor="context-budget",
            kind="context_budget",
            payload=pressure_payload(pressure, context_budget, context_meter),
            causal_parent=plan_entry.seq,
        )
elif ctx and len(ctx) > max_upstream_chars:
    ctx = ctx[:max_upstream_chars] + "\n... [truncated for prompt efficiency]"
if ctx:
    task_parent = ledger.append(
        actor="context", kind="context",
        payload={"task": task.id, "context": ctx}, causal_parent=plan_entry.seq,
    ).seq
    instruction = instruction + "\n\nContext for this task:\n" + ctx
```

- [ ] **Step 8: Run dispatch and request-level tests**

Run:

```bash
python -m pytest tests/test_context.py tests/test_dispatch.py tests/test_context_budget.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 2 and Task 3 together**

```bash
git add src/forum/engine.py src/forum/dispatch.py tests/test_context.py tests/test_dispatch.py
git commit -m "feat: witness context pressure in runs"
```

---

### Task 4: Reporting and Bench Metrics

**Files:**
- Modify: `src/forum/report.py`
- Modify: `tests/test_report.py`

**Interfaces:**
- Consumes: `context_budget` ledger payload shape.
- Produces: `context_budget_checks`, `context_budget_trimmed`, `context_budget_omitted`, `context_tokens_original`, `context_tokens_admitted`, `context_tokens_saved` in summaries and compare deltas.

- [ ] **Step 1: Write failing report tests**

Append to `tests/test_report.py`:

```python
def test_summary_reports_context_pressure_metrics():
    led = _led()
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={
            "schema": "forum.context-pressure/v1",
            "source": "task",
            "label": "T1",
            "action": "trimmed",
            "reason": "max_task_tokens",
            "original_bytes": 40,
            "admitted_bytes": 20,
            "original_tokens": 10,
            "admitted_tokens": 5,
            "remaining_total_tokens": 20,
        },
    )
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={
            "schema": "forum.context-pressure/v1",
            "source": "task",
            "label": "T2",
            "action": "omitted",
            "reason": "max_total_tokens",
            "original_bytes": 16,
            "admitted_bytes": 0,
            "original_tokens": 4,
            "admitted_tokens": 0,
            "remaining_total_tokens": 0,
        },
    )
    s = summarize(led)
    assert s["context_budget_checks"] == 2
    assert s["context_budget_trimmed"] == 1
    assert s["context_budget_omitted"] == 1
    assert s["context_tokens_original"] == 14
    assert s["context_tokens_admitted"] == 5
    assert s["context_tokens_saved"] == 9
    assert "context_tokens_saved" in compare(s, s)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_report.py::test_summary_reports_context_pressure_metrics -q
```

Expected: FAIL with `KeyError: 'context_budget_checks'`.

- [ ] **Step 3: Add summary metric extraction**

In `src/forum/report.py`, after the `revisions_accepted` line, add:

```python
    context_budget_entries = ledger.query(kind="context_budget")
    context_budget_payloads = [ledger.get_payload(e.payload_hash) for e in context_budget_entries]
    context_budget_trimmed = sum(1 for p in context_budget_payloads if p.get("action") == "trimmed")
    context_budget_omitted = sum(1 for p in context_budget_payloads if p.get("action") == "omitted")
    context_tokens_original = sum(int(p.get("original_tokens", 0)) for p in context_budget_payloads)
    context_tokens_admitted = sum(int(p.get("admitted_tokens", 0)) for p in context_budget_payloads)
```

In the returned dict, add:

```python
        "context_budget_checks": len(context_budget_entries),
        "context_budget_trimmed": context_budget_trimmed,
        "context_budget_omitted": context_budget_omitted,
        "context_tokens_original": context_tokens_original,
        "context_tokens_admitted": context_tokens_admitted,
        "context_tokens_saved": context_tokens_original - context_tokens_admitted,
```

In `_NUMERIC`, add the same numeric fields:

```python
    "context_budget_checks", "context_budget_trimmed", "context_budget_omitted",
    "context_tokens_original", "context_tokens_admitted", "context_tokens_saved",
```

- [ ] **Step 4: Run report tests**

Run:

```bash
python -m pytest tests/test_report.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/forum/report.py tests/test_report.py
git commit -m "feat: report context pressure metrics"
```

---

### Task 5: Receipts and Public Surface Budget Parsing

**Files:**
- Modify: `src/forum/receipts.py`
- Modify: `src/forum/cli.py`
- Modify: `src/forum/http_surface.py`
- Modify: `src/forum/mcp_surface.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: `ContextBudget`, report-style context pressure metrics, and `Orchestrator.submit(request, context_budget=budget)`.
- Produces: CLI flags, HTTP JSON fields, MCP fields, and receipt `context_budget` block.

- [ ] **Step 1: Add failing receipt test in an existing surface test**

Append to `tests/test_cli.py`:

```python
def test_context_budget_flags_parse():
    parser = build_parser()
    args = parser.parse_args([
        "submit",
        "build",
        "--cmd",
        "echo",
        "--context-token-budget",
        "100",
        "--request-context-token-budget",
        "50",
        "--task-context-token-budget",
        "25",
        "--upstream-token-budget",
        "10",
    ])
    assert args.context_token_budget == 100
    assert args.request_context_token_budget == 50
    assert args.task_context_token_budget == 25
    assert args.upstream_token_budget == 10
```

This test assumes `build_parser` is already imported in `tests/test_cli.py`. If the file imports only `main`, change the import line to:

```python
from forum.cli import build_parser, main
```

- [ ] **Step 2: Add failing HTTP and MCP tests**

Append to `tests/test_http_surface.py`:

```python
def test_submit_accepts_context_budget_fields():
    surface = _surface(_submit_executor())
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "context_token_budget": 0}',
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert "context_budget" in body["receipt"]
```

Use the existing helper names in the file. If the helper executor is named differently, use the same executor helper already used by the existing successful `/submit` test.

Append to `tests/test_mcp_surface.py`:

```python
def test_prefixed_submit_accepts_context_budget_fields():
    surface = _mcp()
    resp = _call(surface, "forum.submit", {
        "request": "design an api",
        "context_token_budget": 0,
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert "context_budget" in payload["receipt"]
```

- [ ] **Step 3: Run surface tests to verify failures**

Run:

```bash
python -m pytest tests/test_cli.py::test_context_budget_flags_parse tests/test_http_surface.py::test_submit_accepts_context_budget_fields tests/test_mcp_surface.py::test_prefixed_submit_accepts_context_budget_fields -q
```

Expected: FAIL because the flags and receipt fields do not exist yet.

- [ ] **Step 4: Add receipt context budget observed block**

In `src/forum/receipts.py`, add helper:

```python
def _context_budget_observed(entries: list[LedgerEntry], ledger: Ledger) -> dict[str, int]:
    payloads = []
    for entry in entries:
        if entry.kind != "context_budget":
            continue
        try:
            payloads.append(ledger.get_payload(entry.payload_hash))
        except KeyError:
            continue
    original = sum(int(p.get("original_tokens", 0)) for p in payloads)
    admitted = sum(int(p.get("admitted_tokens", 0)) for p in payloads)
    return {
        "checks": len(payloads),
        "trimmed": sum(1 for p in payloads if p.get("action") == "trimmed"),
        "omitted": sum(1 for p in payloads if p.get("action") == "omitted"),
        "tokens_original": original,
        "tokens_admitted": admitted,
        "tokens_saved": original - admitted,
    }
```

Change `submit_receipt` signature:

```python
context_budget: dict[str, Any] | None = None,
```

Add to returned dict:

```python
        "context_budget": {
            "limits": context_budget or {},
            "observed": _context_budget_observed(entries, ledger),
        },
```

- [ ] **Step 5: Add CLI budget construction and flags**

In `src/forum/cli.py`, add helper near `_open_ledger`:

```python
def _make_context_budget(args):
    values = {
        "max_total_tokens": getattr(args, "context_token_budget", None),
        "max_request_tokens": getattr(args, "request_context_token_budget", None),
        "max_task_tokens": getattr(args, "task_context_token_budget", None),
        "max_upstream_tokens": getattr(args, "upstream_token_budget", None),
    }
    if all(value is None for value in values.values()):
        return None, {}
    from forum.context_budget import ContextBudget

    budget = ContextBudget(**values)
    return budget, budget.configured_limits()
```

In `_cmd_submit`, after `budget_payload = {}`, add:

```python
    try:
        context_budget, context_budget_payload = _make_context_budget(args)
    except ValueError as exc:
        print(f"invalid context budget: {exc}", file=sys.stderr)
        return 2
```

Change submit call:

```python
answer = asyncio.run(orch.submit(args.request, budget=budget, context_budget=context_budget))
```

Change receipt call:

```python
context_budget=context_budget_payload,
```

In parser setup for `submit`, add:

```python
    submit.add_argument("--context-token-budget", type=int, default=None, help="bound admitted context across the run to N approximate tokens")
    submit.add_argument("--request-context-token-budget", type=int, default=None, help="bound request-level context to N approximate tokens")
    submit.add_argument("--task-context-token-budget", type=int, default=None, help="bound each per-task context slice to N approximate tokens")
    submit.add_argument("--upstream-token-budget", type=int, default=None, help="bound each upstream result injection to N approximate tokens")
```

- [ ] **Step 6: Add HTTP parsing**

In `src/forum/http_surface.py`, add helper method inside `HttpSurface`:

```python
    def _context_budget(self, data: dict):
        from forum.context_budget import ContextBudget

        mapping = {
            "context_token_budget": "max_total_tokens",
            "request_context_token_budget": "max_request_tokens",
            "task_context_token_budget": "max_task_tokens",
            "upstream_token_budget": "max_upstream_tokens",
        }
        kwargs = {}
        for field, target in mapping.items():
            if field not in data:
                continue
            value = data[field]
            if not isinstance(value, int):
                return None, None, error(400, f"field {field!r} must be an integer")
            kwargs[target] = value
        if not kwargs:
            return None, {}, None
        try:
            budget = ContextBudget(**kwargs)
        except ValueError as exc:
            return None, None, error(400, str(exc))
        return budget, budget.configured_limits(), None
```

In `_submit`, before `before_seq`, add:

```python
        context_budget, context_budget_payload, err = self._context_budget(data)
        if err:
            return err
```

Change submit and receipt calls:

```python
answer = await self._orch.submit(request, context_budget=context_budget)
```

```python
context_budget=context_budget_payload,
```

- [ ] **Step 7: Pass MCP submit budget fields through HTTP**

In `src/forum/mcp_surface.py`, replace the submit lambda with a helper:

```python
def _submit_body(arguments: dict) -> bytes:
    body = {"request": arguments.get("request", "")}
    for key in (
        "context_token_budget",
        "request_context_token_budget",
        "task_context_token_budget",
        "upstream_token_budget",
    ):
        if key in arguments:
            body[key] = arguments[key]
    return _body(body)
```

Change `_TOOL_ROUTES` submit entry:

```python
    "submit": lambda a: ("POST", "/submit", _submit_body(a)),
```

Update both `submit` and `forum.submit` tool schemas to include:

```python
"context_token_budget": {"type": "integer", "description": "run-wide approximate context token budget"},
"request_context_token_budget": {"type": "integer", "description": "request-level context token budget"},
"task_context_token_budget": {"type": "integer", "description": "per-task context token budget"},
"upstream_token_budget": {"type": "integer", "description": "per-upstream injection token budget"},
```

- [ ] **Step 8: Run surface tests**

Run:

```bash
python -m pytest tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/forum/receipts.py src/forum/cli.py src/forum/http_surface.py src/forum/mcp_surface.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py
git commit -m "feat: expose context pressure budgets"
```

---

### Task 6: Documentation and Example

**Files:**
- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CHANGELOG.md`
- Create: `examples/run_context_pressure.py`

**Interfaces:**
- Consumes: public CLI/API behavior from Tasks 1-5.
- Produces: docs that explain context pressure and a runnable example.

- [ ] **Step 1: Add runnable example**

Create `examples/run_context_pressure.py`:

```python
from __future__ import annotations

import asyncio

from forum.context_budget import ContextBudget
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
from forum.roster import loads


ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api"]
model_tier="capable"
executor="echo"
"""
)


class ContextProvider:
    def context(self, request: str) -> str:
        return "important-context " * 80


class Executor:
    async def run(self, assignment):
        if assignment.agent == "coordinator":
            return Result(
                assignment.task_id,
                assignment.agent,
                '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}',
            )
        if assignment.agent == "validator":
            return Result(assignment.task_id, assignment.agent, '{"ok": true, "score": 1.0, "reason": "ok"}')
        if assignment.agent == "synthesizer":
            return Result(assignment.task_id, assignment.agent, "Built the api.")
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER,
        ledger,
        Executor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=1),
        context_provider=ContextProvider(),
    )
    answer = asyncio.run(
        orch.submit(
            "build the api",
            context_budget=ContextBudget(max_total_tokens=40, max_request_tokens=20, max_task_tokens=20),
        )
    )
    summary = summarize(ledger)
    print(answer)
    print("context budget checks:", summary["context_budget_checks"])
    print("context tokens saved:", summary["context_tokens_saved"])
    print("ledger verified:", summary["verified"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update README**

In `README.md`, add `python examples/run_context_pressure.py` to the examples list near `run_efficiency.py`. Add one bullet to the pains list:

```markdown
- **"Large context becomes a hidden bill and a hidden risk."** A `ContextBudget` admits, trims, or omits request context, per-task context, and upstream result injection under approximate-token caps. Every decision is witnessed as `context_budget`, so a run can prove what context shaped it and what was left out. (v1.13)
```

Update the roadmap with:

```markdown
- **1.13, context pressure.** Deterministic approximate-token budgets for request context, per-task context, and upstream injection, with retained/trimmed/omitted decisions witnessed and summarized.
```

- [ ] **Step 3: Update USAGE**

In `USAGE.md`, add:

```markdown
## Context Pressure

```bash
forum submit "ship the api" --cmd "ollama run llama3" --context-token-budget 4000
forum submit "ship the api" --cmd "ollama run llama3" --request-context-token-budget 1000 --task-context-token-budget 800 --upstream-token-budget 800
```

Forum treats these as approximate tokens using the same 4 bytes/token accounting used by Index context envelopes. The ledger records `context_budget` entries for retained, trimmed, and omitted context, and `forum ledger summary --json` reports original, admitted, and saved context tokens.
```

- [ ] **Step 4: Update ARCHITECTURE**

In `ARCHITECTURE.md`, replace the sentence that says context budget and compaction are the next rung with:

```markdown
The context-pressure layer makes that budget explicit. A `ContextBudget` applies model-agnostic approximate-token limits to request-level context, per-task context, and upstream data injection. Each admitted, trimmed, or omitted slice is witnessed as `context_budget`; the normal context entries store only admitted text, and omitted text is represented by counts and a reason rather than raw content.
```

- [ ] **Step 5: Update CHANGELOG**

Under `## Unreleased`, add:

```markdown
- Context pressure: adds `ContextBudget`, deterministic approximate-token accounting, witnessed `context_budget` entries, summary/bench metrics, and CLI/HTTP/MCP budget fields for request context, per-task context, and upstream data injection.
```

- [ ] **Step 6: Run docs/example verification**

Run:

```bash
python examples/run_context_pressure.py
python -m pytest tests/test_context_budget.py tests/test_context.py tests/test_dispatch.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: example prints `ledger verified: True`; tests PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md USAGE.md ARCHITECTURE.md CHANGELOG.md examples/run_context_pressure.py
git commit -m "docs: document context pressure workflow"
```

---

### Task 7: Final Verification

**Files:**
- Read-only verification across the working tree.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence that the implementation satisfies the Context Pressure spec.

- [ ] **Step 1: Run targeted test slice**

```bash
python -m pytest tests/test_context_budget.py tests/test_context.py tests/test_dispatch.py tests/test_budget.py tests/test_report.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 2: Run package-facing checks**

```bash
forum status --json
forum doctor --json
python examples/run_context_pressure.py
```

Expected: `forum status --json` and `forum doctor --json` emit JSON action envelopes; the example prints `ledger verified: True`.

- [ ] **Step 3: Optional full suite if targeted slice passes**

Run this because the change crosses CLI, HTTP, MCP, dispatcher, engine, reports, and docs:

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Inspect git diff and secret hygiene**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended files changed or a clean branch after commits. No `.env`, credentials, or private payloads are staged.

- [ ] **Step 5: Final commit if any verification-only fixes were needed**

If previous steps required code or docs fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize context pressure verification"
```

If no fixes were needed, do not create an empty commit.
