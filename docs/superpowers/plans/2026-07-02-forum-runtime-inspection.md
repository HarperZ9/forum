# Forum Runtime Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `forum runtime inspect` surface that explains the local default and tier executor policy before a run starts.

**Architecture:** Keep runtime inspection separate from executor construction by introducing a small descriptor module. The CLI will parse the same executor/config flags already used by submit, merge them with the same precedence, and pass descriptors into an inspector that joins them to the built-in roster.

**Tech Stack:** Python 3.11, argparse, existing stdlib TOML runtime config, pytest, Ruff.

## Global Constraints

- No command execution or network calls during inspection.
- Never print API key values; only env var names may appear.
- CLI flags override config entries for the same default or tier.
- Preserve existing `submit`, `serve`, and `mcp` executor behavior.
- Keep files focused and under the project 300-line guideline where practical.

---

### Task 1: Runtime Descriptors

**Files:**
- Create: `src/forum/runtime_descriptor.py`
- Modify: `src/forum/runtime_config.py`
- Test: `tests/test_runtime_descriptor.py`

**Interfaces:**
- Produces: `RuntimeExecutorSpec(kind: str, identity: str, source: str, detail: dict[str, str])`
- Produces: `descriptor_from_config(path: str | os.PathLike[str]) -> tuple[RuntimeExecutorSpec | None, dict[str, RuntimeExecutorSpec]]`

- [ ] **Step 1: Write failing descriptor tests**

Add tests that load a runtime config with `[runtime.default]`, `[runtime.tiers.cheap]`, and `[runtime.tiers.capable]`, then assert chat and command descriptors without constructing executors.

- [ ] **Step 2: Run red**

Run: `pytest tests/test_runtime_descriptor.py -q`
Expected: FAIL because `forum.runtime_descriptor` does not exist.

- [ ] **Step 3: Implement descriptors**

Add a frozen dataclass and config parsing path that reuses TOML validation rules, reports `kind` as `chat` or `cmd`, `identity` as the model id or `SubprocessExecutor`, and stores safe details such as `base_url`, `model`, `api_key_env`, or command argv preview.

- [ ] **Step 4: Run green**

Run: `pytest tests/test_runtime_descriptor.py -q`
Expected: PASS.

### Task 2: Runtime Inspection

**Files:**
- Create: `src/forum/runtime_inspect.py`
- Test: `tests/test_runtime_inspect.py`

**Interfaces:**
- Consumes: `RuntimeExecutorSpec`
- Produces: `inspect_runtime(default, tiers, roster) -> dict`
- Produces: `runtime_inspect_text(payload: dict) -> str`

- [ ] **Step 1: Write failing inspection tests**

Add tests for a ready mixed runtime, fallback tier behavior, and missing default/tier issues.

- [ ] **Step 2: Run red**

Run: `pytest tests/test_runtime_inspect.py -q`
Expected: FAIL because `forum.runtime_inspect` does not exist.

- [ ] **Step 3: Implement inspection**

Join the descriptor map to `load_default()` roster counts. Build `forum.runtime.inspect/v1`, `ready`, `default`, `tiers`, `roster`, and `issues`.

- [ ] **Step 4: Run green**

Run: `pytest tests/test_runtime_inspect.py -q`
Expected: PASS.

### Task 3: CLI Surface

**Files:**
- Modify: `src/forum/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `RUNNING.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Consumes: `_add_executor(sp)`
- Produces: `forum runtime inspect [--json] [executor flags...]`

- [ ] **Step 1: Write failing CLI tests**

Add tests for `forum runtime inspect --json --runtime-config <path>` and the text output mode.

- [ ] **Step 2: Run red**

Run: `pytest tests/test_cli.py -q`
Expected: FAIL because `runtime` is not a registered subcommand.

- [ ] **Step 3: Implement CLI**

Add `_cmd_runtime_inspect(args)`, a `runtime` subparser with `inspect`, attach `_add_executor`, and print JSON or text.

- [ ] **Step 4: Run targeted verification**

Run: `pytest tests/test_runtime_descriptor.py tests/test_runtime_inspect.py tests/test_cli.py -q`
Expected: PASS.

### Task 4: Final Verification

**Files:**
- All changed files

- [ ] **Step 1: Run Ruff**

Run: `python -m ruff check src/forum/runtime_descriptor.py src/forum/runtime_inspect.py src/forum/runtime_config.py src/forum/cli.py tests/test_runtime_descriptor.py tests/test_runtime_inspect.py tests/test_cli.py`
Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

Run staged whitespace and focused secret checks, then commit with:

```bash
git commit -m "feat: add runtime inspection surface"
```

## Self-Review

- Spec coverage: descriptors, inspection payload, CLI JSON/text, docs, and verification are covered.
- Placeholder scan: no TBD/TODO/fill-in sections.
- Type consistency: descriptor names and inspector signatures are consistent across tasks.
