# Forum Usage

Forum coordinates agents and model executors through a replayable causal
ledger. It is designed for local CLIs, MCP hosts, HTTP adapters, and larger
Project Telos workflows that need a trustworthy path from request to answer.

## Install

```bash
python -m pip install forum-engine
```

From a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
forum status --json
forum doctor --json
forum demo --json
forum --help
```

Example scripts:

```bash
python examples/demo.py
python examples/run_request.py
python examples/run_resume.py
python examples/run_context_pressure.py
```

## Context Pressure

```bash
forum submit "ship the api" --cmd "ollama run llama3" --context-token-budget 4000
forum submit "ship the api" --cmd "ollama run llama3" --request-context-token-budget 1000 --task-context-token-budget 800 --upstream-token-budget 800
```

Forum treats these as approximate tokens using the same 4 bytes/token accounting used
by Index context envelopes. The ledger records `context_budget` entries for retained,
trimmed, and omitted context, and `forum ledger summary --json` reports original,
admitted, and saved context tokens.

## MCP

Use `forum mcp` when a host needs Forum over stdio.

```bash
forum mcp
```

## Verify

```bash
python -m pytest
python examples/demo.py
```

For public/developer delivery checks:

```bash
python -m public_surface_sweeper . --workspace --json
```

## Boundary

Forum should expose route ids, ledger sequence, payload hashes, model identity,
validation verdicts, and receipt references. Do not require raw private prompts,
credentials, full tool payloads, or private evidence for interop.
