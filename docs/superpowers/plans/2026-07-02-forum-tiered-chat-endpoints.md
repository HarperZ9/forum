# Forum Tiered Chat Endpoints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-tier OpenAI-compatible chat endpoint flags so Forum can map roster tiers directly to local model servers.

**Architecture:** Extend the existing CLI executor factory. Keep global executor priority unchanged, add tier chat constructors that produce `ChatExecutor`s, and feed them into the existing `TieredExecutor` wrapper. Tier chat executors take precedence over tier command executors for the same tier.

**Tech Stack:** Python 3.11, existing Forum CLI argparse, `ChatExecutor`, `SubprocessExecutor`, `TieredExecutor`, pytest.

## Global Constraints

- No new runtime dependencies.
- Existing `--cmd`, `--chat-url`, `--api`, and tier command behavior remains unchanged when tier chat flags are absent.
- No real network calls in tests.
- Missing per-tier model names default to the tier name.

---

## File Structure

- Modify `tests/test_cli.py`: add per-tier chat endpoint factory tests.
- Modify `src/forum/cli.py`: parse per-tier chat flags and build tier `ChatExecutor`s.
- Modify `README.md`, `ARCHITECTURE.md`: document tier endpoint mapping.

---

### Task 1: CLI Tier Chat Constructors

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/forum/cli.py`

**Interfaces:**
- Consumes: `ChatExecutor`, `TieredExecutor`
- Produces parser args `<tier>_chat_url`, `<tier>_model`, `<tier>_api_key_env`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
def test_tier_chat_flags_build_chat_executors():
    from forum.chat_executor import ChatExecutor
    from forum.executor import Assignment
    from forum.runtime import TieredExecutor

    args = build_parser().parse_args([
        "submit",
        "do x",
        "--cmd",
        "base-model",
        "--cheap-chat-url",
        "http://cheap/v1/chat/completions",
        "--cheap-model",
        "phi3",
        "--capable-chat-url",
        "http://capable/v1/chat/completions",
        "--capable-model",
        "llama3",
    ])
    executor = _make_executor(args)

    cheap = executor.select(Assignment("T1", "technical-writing", "docs"))
    capable = executor.select(Assignment("T2", "backend", "build"))
    control = executor.select(Assignment("control:coordinator", "coordinator", "plan"))
    assert isinstance(executor, TieredExecutor)
    assert isinstance(cheap, ChatExecutor)
    assert isinstance(capable, ChatExecutor)
    assert cheap._base_url == "http://cheap/v1/chat/completions"
    assert cheap.model_id == "phi3"
    assert capable._base_url == "http://capable/v1/chat/completions"
    assert capable.model_id == "llama3"
    assert control._command == ["base-model"]
```

Add:

```python
def test_tier_chat_defaults_model_to_tier_name_and_overrides_tier_cmd():
    from forum.chat_executor import ChatExecutor
    from forum.executor import Assignment

    args = build_parser().parse_args([
        "submit",
        "do x",
        "--capable-cmd",
        "capable-cli",
        "--capable-chat-url",
        "http://capable/v1/chat/completions",
    ])
    executor = _make_executor(args)

    capable = executor.select(Assignment("T1", "backend", "build"))
    assert isinstance(capable, ChatExecutor)
    assert capable.model_id == "capable"
    assert capable._base_url == "http://capable/v1/chat/completions"
```

Add:

```python
def test_tier_chat_flags_are_available_on_serve_and_mcp():
    serve = build_parser().parse_args([
        "serve",
        "--capable-chat-url",
        "http://capable/v1/chat/completions",
    ])
    mcp = build_parser().parse_args([
        "mcp",
        "--frontier-chat-url",
        "http://frontier/v1/chat/completions",
        "--frontier-model",
        "qwen",
    ])

    assert serve.capable_chat_url.endswith("/chat/completions")
    assert mcp.frontier_model == "qwen"
```

- [ ] **Step 2: Run red tests**

```powershell
python -m pytest tests/test_cli.py::test_tier_chat_flags_build_chat_executors tests/test_cli.py::test_tier_chat_defaults_model_to_tier_name_and_overrides_tier_cmd tests/test_cli.py::test_tier_chat_flags_are_available_on_serve_and_mcp -q
```

Expected: FAIL because the flags do not exist.

- [ ] **Step 3: Implement parser flags and constructors**

In `src/forum/cli.py`, add `_tier_chat_executor(args, tier)`, call it from
`_tier_executors`, and add the per-tier flags in `_add_executor`.

- [ ] **Step 4: Run green tests**

```powershell
python -m pytest tests/test_cli.py::test_tier_chat_flags_build_chat_executors tests/test_cli.py::test_tier_chat_defaults_model_to_tier_name_and_overrides_tier_cmd tests/test_cli.py::test_tier_chat_flags_are_available_on_serve_and_mcp -q
```

Expected: PASS.

---

### Task 2: Docs and Verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Update docs**

Document direct per-tier endpoint mapping with `--cheap-chat-url`,
`--capable-chat-url`, and `--frontier-chat-url`.

- [ ] **Step 2: Run targeted tests**

```powershell
python -m pytest tests/test_cli.py tests/test_chat_executor.py tests/test_runtime.py tests/test_dispatch.py tests/test_engine.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full suite**

```powershell
python -m pytest -q
```

Expected: PASS.
