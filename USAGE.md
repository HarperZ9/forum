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
```

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
