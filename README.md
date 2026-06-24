# Forum

**Accountable orchestration for multi-agent systems — the core, zero dependencies.**

[![CI](https://github.com/HarperZ9/forum/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/forum/actions/workflows/ci.yml)
![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![deps: none](https://img.shields.io/badge/deps-none-success.svg)
![tests: 29](https://img.shields.io/badge/tests-29%20passing-success.svg)

A stateless model can't remember what it did, and a log it only *claims* is correct
isn't worth much. Forum is the part of a multi-agent orchestrator that addresses
both: it routes work to the right specialist, plans dependencies, and writes every
decision and result into a **tamper-evident ledger you can verify and replay** — a
record you check, not one you trust.

This repository is the **core foundation (v0.1)**: pure Python standard library, no
third-party runtime dependencies, and it's the part that's done. The actor runtime,
the HTTP/MCP daemon, and the pluggable executors (Claude Code, raw API, CLI) are the
next milestones — see [Roadmap](#roadmap). It's a library you wire into your own
loop, not a platform.

## What's here today

| Module | What it does |
|---|---|
| `forum.ledger` | Append-only, hash-chained, content-addressed ledger: `verify()` (chain, plus optional deep payload-body check), `replay()`, `causal_chain()`, domain-separated Merkle `checkpoint()`. Any mutation, reorder, or gap is caught. |
| `forum.routing` | Deterministic, specificity-aware keyword router. Decides a lane or escalates with a confidence score — no model call for the easy cases. |
| `forum.roster` | Loads and validates a capability roster from TOML. |
| `forum.plan` | Turns a task DAG into ordered parallel waves; detects cycles and unknown dependencies. |
| `forum.policy` | Category scope gate and parallel-wave capping. |

## Quickstart

```bash
git clone https://github.com/HarperZ9/forum
cd forum
python examples/demo.py        # no install, no dependencies
```

To run the tests:

```bash
pip install -e ".[dev]"
pytest
```

## The demo

`python examples/demo.py` routes a few requests, plans a small DAG, witnesses every
step in the ledger, then tampers with a stored result to show the ledger catches it:

```
1. Routing (deterministic Tier-0; decides a lane or escalates)
   'build the database schema and the auth endpoint'  ->  backend
    'build the react component and css for the page'  ->  frontend
               'write the readme docs and the guide'  ->  docs
                                  'summon a unicorn'  ->  escalate -> needs an LLM classifier (confidence 0.00)

2. Planning (DAG -> parallel waves, capped by policy max_parallel=2)
  wave 0: ['T1']
  wave 1: ['T2']
  wave 2: ['T3', 'T4']

4. Accountability: verify, tamper-detect, replay
  verify() (chain)      : True
  verify(deep=True)     : True
  causal chain of last  : request -> plan -> task -> result

   ...now tamper with a stored payload body (seq 2)
  verify() (chain only) : True   <- chain hashes still link
  verify(deep=True)     : False  <- body tamper caught
```

## Why a ledger, specifically

The hard problem behind agent systems isn't calling models — it's giving a stateless
model **durable, verified contact with state**. The work a fleet does needs a record
that (a) outlives any one context window and (b) can be *checked* rather than
trusted. Forum's ledger is content-addressed and hash-chained, so:

- any mutation, reordering, or gap is caught by `verify()`;
- payload bodies can be re-checked (`verify(deep=True)`), or stored hash-only / redacted without breaking the chain;
- `replay()` reconstructs exact past state, and `causal_chain()` walks the *why* behind any result.

The Merkle checkpoint domain-separates leaves from internal nodes (RFC 6962 style)
and promotes odd nodes instead of duplicating them, so it doesn't have the classic
second-preimage weakness (CVE-2012-2459).

## Roadmap

- **v0.1 (here)** — witnessed ledger, deterministic routing, roster, DAG planner, policy. 29 tests.
- **next** — an `asyncio` actor / supervision runtime and the control loop: classify → coordinate → validate → synthesize.
- **then** — pluggable executors (Claude Code subagents, raw API, CLI) and an HTTP + MCP daemon, for an end-to-end witnessed run.

## Design

[ARCHITECTURE.md](ARCHITECTURE.md) covers the layered design and the ledger mechanics.

## License

MIT — see [LICENSE](LICENSE). Part of a small toolkit of zero-dependency
building blocks for accountable AI systems.
