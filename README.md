# Forum

[![CI](https://github.com/HarperZ9/forum/actions/workflows/ci.yml/badge.svg)](https://github.com/HarperZ9/forum/actions/workflows/ci.yml)
![license: fair-source](https://img.shields.io/badge/license-fair--source-blue.svg)
![python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![deps: none](https://img.shields.io/badge/deps-none-success.svg)

Every few months there's a new framework for orchestrating AI agents. You wire one
up, hand it a task, and it works. Then you try to run it for real, and you hit the
question that actually matters: what happened on that run, and can you prove it?
Usually all you've got is a pile of model output and a log you're supposed to trust.

Forum starts from that question. It's an orchestration engine for fleets of agents,
and the idea underneath it is simple. The record of what happened isn't a side effect
of the work. It is the work. Every routing decision, every task, every result goes
into a ledger you can verify, replay, and trace. Think of how a bank reconciles its
books instead of trusting the teller's memory.

Here's why it's built this way. A language model has no memory of its own. Each call
starts from nothing. If you want to build something dependable on top of that, you
have to give a forgetful mind two things it can't supply for itself: a record that
outlives the conversation, and a way to check that record instead of trusting it. You
also need reach, the ability to act across a lot of agents at once. That's the real
project. The small zero-dependency pieces in this repo aren't the goal. They're the
bricks.

This is the first layer of them. What's here is the foundation: the ledger, the
router, the planner. It runs today, and you can watch it catch a tampered record in
about twenty lines. The rest goes up next (see the [roadmap](#roadmap)): a live
runtime, the executors that drive real models, and a daemon to hold it together.

## Watch it work

```bash
git clone https://github.com/HarperZ9/forum
cd forum
python examples/demo.py        # no install, nothing to download
```

The demo routes a few requests, plans a small dependency graph, records every step,
and then does the interesting part. It quietly corrupts a stored result and checks
whether the ledger notices.

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

Look at those last two lines. The chain of hashes still links, so a quick check
passes. But the contents of one record no longer match what was promised, and the
deeper check says so. You don't have to trust the record. You can check it.

## How the ledger works

A log tells you what a program says it did. A ledger lets you prove it. Two old ideas
do most of the work.

The first is a hash chain. Every entry carries a fingerprint of the one before it.
Edit a past entry, drop one, or shuffle the order, and the fingerprints stop lining
up. `verify()` walks the chain and tells you where.

The second is content addressing. The bulky parts, the prompts and the outputs, are
stored under a fingerprint of their own bytes rather than inline. That keeps the chain
small, and it has a useful side effect: you can redact a sensitive body down to its
fingerprint and the chain still checks out. When the bodies are there,
`verify(deep=True)` re-hashes each one to make sure it still matches. That's what
catches the swapped result in the demo.

Everything else falls out of those two. `replay(until=...)` rebuilds the exact state
at any past point, which works because the core is pure and entries never change.
`causal_chain(seq)` follows the parent links to answer the question every postmortem
comes back to: why did this happen? And `checkpoint()` folds the whole history into
one Merkle root. The leaves and the internal nodes are tagged differently, and odd
nodes get carried up rather than duplicated, so it avoids the second-preimage
collision (CVE-2012-2459) that naive Merkle code runs into.

## What's here

- `forum.ledger`: the record. Hash chain, content-addressed bodies, `verify` / `verify(deep=True)`, `replay`, `causal_chain`, Merkle `checkpoint`.
- `forum.routing`: a router that reads a request, picks a lane, and only falls back to a model when the keywords genuinely can't decide.
- `forum.plan`: a task graph compiled into parallel waves, with cycles and missing dependencies caught up front.
- `forum.roster`: the cast of specialists, written as plain data in a TOML file and validated on load.
- `forum.policy`: the rules of the room. Which work can run, and how much at once.

Pure standard library. No third-party runtime dependencies. The tests run the
primitives directly, tamper detection and the Merkle property included.

## Roadmap

- **Today, the foundation.** Ledger, router, roster, planner, policy. It runs and it's tested.
- **Next, the runtime.** An asyncio actor and supervision layer, and the control loop that turns a request into a plan: classify, coordinate, validate, synthesize.
- **Then, reach.** Executors that drive real models (Claude Code subagents, a raw API, a CLI) behind one interface, and an HTTP and MCP daemon, so a whole fleet can run against something larger than a single conversation. Every step still written down, still checkable.

## Design

[ARCHITECTURE.md](ARCHITECTURE.md) goes deeper on the layers and the ledger.

## License

Forum is fair-source: the code is open to read, run, and build on, with commercial
use reserved so the project can fund its own development. Copyright stays with the
author. See [LICENSE](LICENSE) for the exact terms.
