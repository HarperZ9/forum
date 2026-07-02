# Forum Context Capsules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic Context Capsules that compact a Forum ledger into a small reusable context brief, expose it through CLI/HTTP/MCP, and let CLI submit opt into using it as request context.

**Architecture:** Add a pure `forum.context_capsule` module that reads a `Ledger` and returns JSON-ready capsule payloads plus prompt-safe text. Public surfaces reuse existing ledger inspection paths; CLI submit attaches a `LedgerCapsuleProvider` to the orchestrator when requested, so the existing `ContextProvider` and `ContextBudget` paths do the admission and witnessing.

**Tech Stack:** Python standard library only, existing `Ledger`, `ContextProvider`, CLI `argparse`, stdlib HTTP surface, MCP JSON-RPC adapter, pytest.

## Global Constraints

- No third-party runtime dependencies.
- No model call is allowed for capsule generation.
- Capsules must be deterministic for a fixed ledger and options.
- Long payload strings are clipped locally; no raw copied string may exceed `max_text_chars`.
- Empty ledgers return valid capsules.
- Submit capsule context is CLI-only in this slice; HTTP and MCP expose capsule read tools.

---

## File Structure

- Create `src/forum/context_capsule.py`: pure capsule builder, text renderer, and `LedgerCapsuleProvider`.
- Create `tests/test_context_capsule.py`: pure core tests.
- Modify `src/forum/cli.py`: add `forum ledger capsule`, add `--use-capsule-context` to submit, and attach the provider.
- Modify `tests/test_cli.py`: CLI capsule and submit-context tests.
- Modify `src/forum/http_surface.py`: add `GET /capsule`.
- Modify `tests/test_http_surface.py`: HTTP capsule test.
- Modify `src/forum/mcp_surface.py`: add `forum.ledger.capsule`.
- Modify `tests/test_mcp_surface.py`: MCP capsule listing and call tests.
- Create `examples/run_context_capsule.py`: dependency-free example.
- Modify `README.md`, `USAGE.md`, `ARCHITECTURE.md`, `CHANGELOG.md`: document the feature.

---

### Task 1: Pure Context Capsule Core

**Files:**
- Create: `src/forum/context_capsule.py`
- Create: `tests/test_context_capsule.py`

**Interfaces:**
- Consumes: `forum.ledger.Ledger`
- Produces:
  - `CONTEXT_CAPSULE_SCHEMA = "forum.context-capsule/v1"`
  - `build_context_capsule(ledger: Ledger, *, max_items: int = 8, max_text_chars: int = 240) -> dict`
  - `capsule_text(capsule: dict) -> str`
  - `LedgerCapsuleProvider(ledger: Ledger, *, max_items: int = 8, max_text_chars: int = 240).context(request: str) -> str`

- [ ] **Step 1: Write failing core tests**

Create `tests/test_context_capsule.py`:

```python
from forum.context_capsule import (
    CONTEXT_CAPSULE_SCHEMA,
    LedgerCapsuleProvider,
    build_context_capsule,
    capsule_text,
)
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_run():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"text": "build the api"})
    led.append(actor="dispatch", kind="task", payload={"id": "T1", "agent": "backend", "instruction": "build"})
    led.append(
        actor="backend",
        kind="result",
        payload={"id": "T1", "output": "built api with schema", "ok": True, "model": "local-small"},
    )
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 0.9, "reason": "ok"})
    led.append(actor="synthesizer", kind="result", payload={"answer": "The api is built."})
    led.append(actor="intent", kind="intent_check", payload={"flagged": False, "coverage": 1.0, "missing": []})
    led.append(actor="delivery", kind="delivery_check", payload={"flagged": False, "words": 4})
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={"original_tokens": 20, "admitted_tokens": 8, "action": "trimmed"},
    )
    return led


def test_capsule_empty_ledger_is_valid():
    capsule = build_context_capsule(_ledger())
    assert capsule["schema"] == CONTEXT_CAPSULE_SCHEMA
    assert capsule["entry_range"] == [None, None]
    assert capsule["latest_request"] == ""
    assert capsule["latest_answer"] == ""
    assert capsule["tasks"] == []
    assert capsule["verified"] is True
    assert len(capsule["checkpoint"]) == 64


def test_capsule_extracts_latest_request_answer_tasks_and_signals():
    led = _seed_run()
    capsule = build_context_capsule(led, max_items=4, max_text_chars=40)
    assert capsule["schema"] == CONTEXT_CAPSULE_SCHEMA
    assert capsule["checkpoint"] == led.checkpoint()
    assert capsule["entry_range"] == [0, 7]
    assert capsule["latest_request"] == "build the api"
    assert capsule["latest_answer"] == "The api is built."
    assert capsule["counts"]["result"] == 2
    assert capsule["tasks"] == [{
        "seq": 2,
        "id": "T1",
        "agent": "backend",
        "ok": True,
        "model": "local-small",
        "output": "built api with schema",
    }]
    assert capsule["signals"]["context_tokens_saved"] == 12
    assert capsule["context_text_chars"] == len(capsule_text(capsule))


def test_capsule_clips_long_text_and_caps_tasks():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"text": "x" * 40})
    for i in range(3):
        led.append(
            actor="worker",
            kind="result",
            payload={"id": f"T{i}", "output": "y" * 40, "ok": True, "model": "m"},
        )
    capsule = build_context_capsule(led, max_items=2, max_text_chars=10)
    assert capsule["latest_request"] == "xxxxxxx..."
    assert [task["id"] for task in capsule["tasks"]] == ["T1", "T2"]
    assert all(task["output"].endswith("...") for task in capsule["tasks"])


def test_capsule_text_is_compact_and_prompt_safe():
    capsule = build_context_capsule(_seed_run())
    text = capsule_text(capsule)
    assert "Forum context capsule" in text
    assert "latest request: build the api" in text
    assert "latest answer: The api is built." in text
    assert "context_tokens_saved=12" in text
    assert len(text) == capsule["context_text_chars"]


def test_ledger_capsule_provider_returns_rendered_capsule():
    led = _seed_run()
    provider = LedgerCapsuleProvider(led)
    text = provider.context("next request")
    assert "Forum context capsule" in text
    assert "latest answer: The api is built." in text
```

- [ ] **Step 2: Run pure tests to verify they fail**

Run:

```bash
python -m pytest tests/test_context_capsule.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'forum.context_capsule'`.

- [ ] **Step 3: Implement `src/forum/context_capsule.py`**

Add the pure module with deterministic extraction, clipping, and rendering:

```python
from __future__ import annotations

from collections import Counter
from typing import Any

from forum.ledger import Ledger

CONTEXT_CAPSULE_SCHEMA = "forum.context-capsule/v1"


def build_context_capsule(ledger: Ledger, *, max_items: int = 8, max_text_chars: int = 240) -> dict:
    if max_items < 0:
        raise ValueError("max_items must be >= 0")
    if max_text_chars < 0:
        raise ValueError("max_text_chars must be >= 0")
    entries = ledger.replay()
    counts = Counter(entry.kind for entry in entries)
    payloads = [(entry, _payload(ledger, entry.payload_hash)) for entry in entries]

    capsule = {
        "schema": CONTEXT_CAPSULE_SCHEMA,
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(),
        "entry_range": [entries[0].seq, entries[-1].seq] if entries else [None, None],
        "counts": dict(counts),
        "latest_request": _latest_request(payloads, max_text_chars),
        "latest_answer": _latest_answer(payloads, max_text_chars),
        "tasks": _tasks(payloads, max_items, max_text_chars),
        "signals": _signals(payloads, counts),
    }
    capsule["context_text_chars"] = len(capsule_text(capsule))
    return capsule


def capsule_text(capsule: dict) -> str:
    lines = [
        "Forum context capsule",
        f"checkpoint: {capsule.get('checkpoint', '')}",
        f"verified: {capsule.get('verified', False)}",
    ]
    request = capsule.get("latest_request") or ""
    answer = capsule.get("latest_answer") or ""
    if request:
        lines.append(f"latest request: {request}")
    if answer:
        lines.append(f"latest answer: {answer}")
    tasks = capsule.get("tasks") or []
    if tasks:
        lines.append("tasks:")
        for task in tasks:
            lines.append(
                f"- {task.get('id', '')}/{task.get('agent', '')} "
                f"ok={task.get('ok')} model={task.get('model', '')}: {task.get('output', '')}"
            )
    signals = capsule.get("signals") or {}
    if signals:
        ordered = " ".join(f"{key}={signals[key]}" for key in sorted(signals))
        lines.append(f"signals: {ordered}")
    return "\n".join(lines)


class LedgerCapsuleProvider:
    def __init__(self, ledger: Ledger, *, max_items: int = 8, max_text_chars: int = 240) -> None:
        self._ledger = ledger
        self._max_items = max_items
        self._max_text_chars = max_text_chars

    def context(self, request: str) -> str:
        capsule = build_context_capsule(
            self._ledger,
            max_items=self._max_items,
            max_text_chars=self._max_text_chars,
        )
        return capsule_text(capsule)
```

Add private helpers with these behaviors:

- `_payload(ledger, payload_hash)` returns the payload dict, or `{}` when the body is missing or not a dict.
- `_clip(text, max_chars)` returns `text` unchanged when it fits, returns `""` when `max_chars == 0`, and otherwise returns `text[:max_chars - 3] + "..."`.
- `_latest_request(payloads, max_text_chars)` scans reversed payloads for kind `request` with string field `text`.
- `_latest_answer(payloads, max_text_chars)` scans reversed payloads for kind `result` with string field `answer`.
- `_tasks(payloads, max_items, max_text_chars)` keeps result payloads with an `id`, maps entry seq, id, actor as agent fallback, ok, model, and clipped output, then returns the last `max_items`.
- `_signals(payloads, counts)` returns integer counts for failed results, failed verdicts, refuted verifications, flagged intent checks, flagged delivery checks, flagged delivery profile checks, context budget checks, context tokens saved, and budget stops.

- [ ] **Step 4: Run core tests**

Run:

```bash
python -m pytest tests/test_context_capsule.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit core**

```bash
git add src/forum/context_capsule.py tests/test_context_capsule.py
git commit -m "feat: add context capsule core"
```

---

### Task 2: CLI Capsule and Submit Context

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_context_capsule`, `capsule_text`, `LedgerCapsuleProvider`
- Produces:
  - `forum ledger capsule --json`
  - `forum ledger capsule --text`
  - `forum submit ... --use-capsule-context`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_ledger_capsule_json(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "capsule", "--ledger", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["schema"] == "forum.context-capsule/v1"
    assert payload["checkpoint"]
    assert payload["verified"] is True


def test_ledger_capsule_text(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "capsule", "--ledger", str(tmp_path), "--text"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Forum context capsule" in out
    assert "checkpoint:" in out


def test_submit_use_capsule_context_witnesses_context(capsys, tmp_path):
    import sys

    ledger_dir = tmp_path / "ledger"
    _seed(str(ledger_dir))
    model = tmp_path / "model.py"
    model.write_text(
        "import sys\n"
        "text = sys.argv[1]\n"
        "if 'You are a planner' in text:\n"
        "    assert 'Forum context capsule' in text\n"
        "    print('{\"tasks\":[{\"id\":\"T1\",\"agent\":\"backend\",\"instruction\":\"x\",\"depends_on\":[]}]}')\n"
        "elif 'Judge whether the output satisfies' in text:\n"
        "    print('{\"ok\":true,\"score\":0.9,\"reason\":\"ok\"}')\n"
        "elif 'Write the final answer' in text:\n"
        "    print('Done with capsule.')\n"
        "else:\n"
        "    print('handled')\n",
        encoding="utf-8",
    )
    rc = main([
        "submit",
        "design an api",
        "--ledger",
        str(ledger_dir),
        "--cmd",
        f"{sys.executable} {model}",
        "--json",
        "--use-capsule-context",
        "--context-token-budget",
        "1000",
    ])
    body = json.loads(capsys.readouterr().out)
    led = Ledger(FileStorage(str(ledger_dir)))
    contexts = [led.get_payload(e.payload_hash)["context"] for e in led.query(kind="context")]
    assert rc == 0
    assert body["answer"] == "Done with capsule."
    assert any("Forum context capsule" in context for context in contexts)
```

- [ ] **Step 2: Run CLI tests to verify failures**

Run:

```bash
python -m pytest tests/test_cli.py::test_ledger_capsule_json tests/test_cli.py::test_ledger_capsule_text tests/test_cli.py::test_submit_use_capsule_context_witnesses_context -q
```

Expected: FAIL because the command and flag do not exist.

- [ ] **Step 3: Implement CLI command and flag**

In `src/forum/cli.py`:

- Add `_cmd_ledger_capsule(args)` that opens the ledger, builds a capsule with
  `args.max_items` and `args.max_text_chars`, and prints JSON unless `--text` is set.
- Add `capsule` under the `ledger` subparser with `--json`, `--text`,
  `--max-items`, and `--max-text-chars`.
- Add `submit.add_argument("--use-capsule-context", action="store_true", ...)`.
- In `_cmd_submit`, after `orch = build_orchestrator(...)`, set:

```python
    if args.use_capsule_context:
        from forum.context_capsule import LedgerCapsuleProvider

        orch.context_provider = LedgerCapsuleProvider(orch.ledger)
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
python -m pytest tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit CLI**

```bash
git add src/forum/cli.py tests/test_cli.py
git commit -m "feat: expose context capsules in cli"
```

---

### Task 3: HTTP and MCP Capsule Surfaces

**Files:**
- Modify: `src/forum/http_surface.py`
- Modify: `src/forum/mcp_surface.py`
- Modify: `tests/test_http_surface.py`
- Modify: `tests/test_mcp_surface.py`

**Interfaces:**
- Consumes: `build_context_capsule`
- Produces:
  - `GET /capsule`
  - MCP tool `forum.ledger.capsule`

- [ ] **Step 1: Add failing HTTP/MCP tests**

Append to `tests/test_http_surface.py`:

```python
def test_capsule_returns_context_capsule():
    surface, _ = _surface()
    _do(surface, "POST", "/submit", b'{"request": "design an api"}')
    resp = _do(surface, "GET", "/capsule")
    body = json.loads(resp.body)
    assert resp.status == 200
    assert body["schema"] == "forum.context-capsule/v1"
    assert body["latest_answer"] == "Done: the api is designed."
```

Update `tests/test_mcp_surface.py`:

```python
def test_tools_list_includes_context_capsule():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "forum.ledger.capsule" in names


def test_call_prefixed_ledger_capsule_after_submit():
    surface = _mcp()
    _call(surface, "forum.submit", {"request": "design an api"})
    payload = json.loads(_call(surface, "forum.ledger.capsule")["result"]["content"][0]["text"])
    assert payload["schema"] == "forum.context-capsule/v1"
    assert payload["latest_answer"] == "Done."
```

- [ ] **Step 2: Run surface tests to verify failures**

Run:

```bash
python -m pytest tests/test_http_surface.py::test_capsule_returns_context_capsule tests/test_mcp_surface.py::test_tools_list_includes_context_capsule tests/test_mcp_surface.py::test_call_prefixed_ledger_capsule_after_submit -q
```

Expected: FAIL because `/capsule` and `forum.ledger.capsule` do not exist.

- [ ] **Step 3: Implement HTTP and MCP surfaces**

In `src/forum/http_surface.py`:

- Add `"/capsule"` to `_KNOWN_PATHS`.
- Route `GET /capsule` to `_capsule`.
- Implement `_capsule()` using `build_context_capsule(self._orch.ledger)`.

In `src/forum/mcp_surface.py`:

- Add `"ledger_capsule": lambda a: ("GET", "/capsule", b"")`.
- Add alias `"forum.ledger.capsule": "ledger_capsule"`.
- Add a tool spec for `forum.ledger.capsule`.

- [ ] **Step 4: Run surface tests**

Run:

```bash
python -m pytest tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit surfaces**

```bash
git add src/forum/http_surface.py src/forum/mcp_surface.py tests/test_http_surface.py tests/test_mcp_surface.py
git commit -m "feat: expose context capsules over http and mcp"
```

---

### Task 4: Documentation and Example

**Files:**
- Create: `examples/run_context_capsule.py`
- Modify: `README.md`
- Modify: `USAGE.md`
- Modify: `ARCHITECTURE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: capsule CLI/core behavior
- Produces: runnable documentation for context capsules

- [ ] **Step 1: Add example**

Create `examples/run_context_capsule.py` with a scripted two-run flow:

```python
"""Forum: context capsules, compact run memory (v1.15).

Run:  python examples/run_context_capsule.py
"""
```

The example should:

- Run a scripted first request into an in-memory ledger.
- Build a capsule and print `capsule schema`, `latest answer`, and `context text chars`.
- Attach `LedgerCapsuleProvider` to a second orchestrator over the same ledger.
- Run a second request and print whether a `context` entry containing `Forum context capsule` was witnessed.

- [ ] **Step 2: Update docs**

Add concise documentation:

- README pains list: raw ledger replay is too large; Context Capsules compact witnessed state.
- README examples list: `python examples/run_context_capsule.py`.
- README module list: mention `forum.context_capsule`.
- README roadmap: `1.15, context capsules`.
- USAGE: add `forum ledger capsule --json`, `forum ledger capsule --text`, and `forum submit ... --use-capsule-context`.
- ARCHITECTURE: add a paragraph in the run contract after context pressure.
- CHANGELOG: add an Unreleased bullet.

- [ ] **Step 3: Verify docs/example**

Run:

```bash
python examples/run_context_capsule.py
python -m pytest tests/test_context_capsule.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: example reports witnessed capsule context, tests PASS.

- [ ] **Step 4: Commit docs**

```bash
git add examples/run_context_capsule.py README.md USAGE.md ARCHITECTURE.md CHANGELOG.md
git commit -m "docs: document context capsules"
```

---

### Task 5: Final Verification

**Files:**
- Read-only verification across the working tree.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence that Context Capsules work and the repo remains healthy.

- [ ] **Step 1: Run targeted tests**

```bash
python -m pytest tests/test_context_capsule.py tests/test_cli.py tests/test_http_surface.py tests/test_mcp_surface.py -q
```

Expected: PASS.

- [ ] **Step 2: Run examples**

```bash
python examples/run_context_capsule.py
python examples/run_context_pressure.py
```

Expected: both run successfully; context capsule example reports witnessed capsule context.

- [ ] **Step 3: Run full suite**

```bash
python -m pytest -q
```

Expected: PASS with the real-model tests skipped unless `FORUM_RUN_REAL=1`.

- [ ] **Step 4: Inspect git state**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; clean branch after commits.
