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
python examples/run_context_capsule.py
python examples/run_delivery_profile.py
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

## Context Capsules

```bash
forum ledger capsule --json
forum ledger capsule --text
forum submit "ship the api" --cmd "ollama run llama3" --use-capsule-context
```

Capsules compact the current ledger into a deterministic `forum.context-capsule/v1`
brief: latest request, latest answer, task results, quality signals, checkpoint, and
verification state. `--use-capsule-context` feeds that brief through the normal
ContextProvider seam, so existing context budgets still decide how much is admitted.

## Deep Verify Benchmark

```bash
forum bench-deep-verify --json
forum bench-deep-verify --entries 1000,10000 --payload-bytes 256,4096 --storage memory --storage file-batched --redaction-ratio 0,0.5,1 --json --out deep-verify.json
```

`bench-deep-verify` measures the scaling cost of the causal ledger's integrity checks.
It reports chain-only `verify()`, payload-only `verify_payloads()`, and full
`verify(deep=True)` timings as a `forum.deep-verify-benchmark/v1` receipt. The
variables are entry count, payload body bytes, storage mode, fsync mode, redaction
ratio, warmups, and repeats. Redacted payload bodies are removed before verification,
so the benchmark also shows the content-addressed trade-off: the chain can still
verify when only fingerprints remain, while deep payload rehashing scales with the
payload bodies that are still present.

## Expert Delivery Profiles

```bash
forum humanize "Prior to launch, utilize the module test output." --profile engineer
forum submit "ship the api" --cmd "ollama run llama3" --delivery-profile engineer --json
```

Profiles are deterministic checks, not named-writer mimicry. `operator` is the default
contract; `engineer`, `researcher`, and `executive` add domain-specific expectations.
Submit runs witness `delivery_profile_check` entries, and `forum ledger summary --json`
reports profile checks and flags.

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
