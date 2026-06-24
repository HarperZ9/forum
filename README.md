# Forum

[![CI](https://github.com/HarperZ9/forum/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/forum/actions/workflows/ci.yml)
![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![deps: none](https://img.shields.io/badge/deps-none-success.svg)

Every few months a new framework offers to orchestrate your AI agents. You wire one
up, hand it a task, and it works — right up until the question that decides whether
you can run it in production: *what actually happened, and can you prove it?* Usually
the answer is a scroll of logs you have to take on faith.

Forum begins at that question instead of arriving at it. It is an orchestration
engine for fleets of AI agents, built on a single discipline: the account of what
happened is not a byproduct of the work — it *is* the work. Every routing decision,
every task, every result is written to a ledger you can verify, replay, and trace,
the way a bank reconciles its books instead of trusting a teller's memory.

There is a deeper reason it's built this way. A language model keeps no memory of its
own; each call starts from nothing. To build something dependable on a forgetful
mind, you have to give it two things it lacks — durable contact with state that
outlives any single conversation, and a way to *check* that state rather than trust
it — along with the reach to act across many agents at once. That is the whole
project. The small zero-dependency pieces you'll find in here are not the point. They
are the bricks.

This is the first course of them. What's laid so far is the foundation — the ledger,
the router, the planner — and it runs today: you can watch it catch a tampered record
in about twenty lines. The walls go up next (see the [roadmap](#the-roadmap)): a live
actor runtime, the executors that drive real models, and a daemon to keep it standing.

## Watch it work

```bash
git clone https://github.com/HarperZ9/forum
cd forum
python examples/demo.py        # no install, nothing to download
```

The demo routes a handful of requests, plans a small dependency graph, records every
step — and then, the part worth watching, quietly corrupts a stored result to see
whether the ledger notices:

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

Those last two lines are the whole idea in miniature. The chain of hashes still
links, so a shallow check passes — but the *contents* of one record no longer match
what was promised, and a deeper check says so out loud. Trust, but verify; and here,
you can actually verify.

## How the ledger earns its keep

A log tells you what a program claims it did. A ledger lets you prove it. The
difference is in two old ideas, borrowed from cryptography and bookkeeping.

First, every entry carries the fingerprint of the one before it — a hash chain. Change
any past entry, drop one, or shuffle the order, and the fingerprints stop matching.
`verify()` walks the chain and notices.

Second, the bulky contents — a prompt, a result — are stored by the fingerprint of
their own bytes, not inline. This keeps the chain light, and it lets you do something
useful: redact a sensitive body to its fingerprint alone, and the chain still
verifies. When the bodies *are* present, `verify(deep=True)` re-checks each one
against its fingerprint, which is how the demo catches a swapped result.

From there the rest follows. `replay(until=...)` reconstructs the exact state at any
past moment, because the core is pure and entries never change. `causal_chain(seq)`
walks the parent links to answer the question every incident review eventually asks:
*why did this happen?* And `checkpoint()` folds the whole history into one Merkle
root — domain-separated and odd-node-promoted, so it sidesteps the classic
second-preimage collision (CVE-2012-2459) that bites naive Merkle code.

## What's standing today

- **`forum.ledger`** — the witnessed record: hash chain, content-addressed bodies, `verify` / `verify(deep=True)`, `replay`, `causal_chain`, Merkle `checkpoint`.
- **`forum.routing`** — a deterministic router that reads a request, picks a lane, and only escalates to a model when the keywords genuinely can't decide.
- **`forum.plan`** — a task graph compiled into ordered parallel waves, with cycles and missing dependencies caught up front.
- **`forum.roster`** — the cast of specialists, written as plain data in a TOML file, validated on load.
- **`forum.policy`** — the rules of the room: which kinds of work may run, and how much at once.

Pure standard library. No third-party runtime dependencies. The tests run the
primitives directly, tamper detection and Merkle collision-resistance included.

## The roadmap

- **Today — the foundation.** The ledger, router, roster, planner, and policy. It runs and it's tested.
- **Next — the runtime.** An `asyncio` actor and supervision layer, and the control loop that turns a request into a plan: classify → coordinate → validate → synthesize.
- **Then — reach.** Executors that drive real models (Claude Code subagents, a raw API, a CLI) behind one interface, and an HTTP + MCP daemon, so a whole fleet can run against a surface larger than any single conversation — every step still written down, still checkable.

## Design

[ARCHITECTURE.md](ARCHITECTURE.md) walks through the layers and the ledger in more depth.

## License

MIT — see [LICENSE](LICENSE).
