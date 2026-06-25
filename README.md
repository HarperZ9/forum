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

This is the first layer of them, and there's enough now to run. The foundation is
here (the ledger, the router, the planner), and so is the runtime on top of it. Forum
can take a multi-step plan, run it across agents, and witness every step, so you can
verify the whole thing afterward. The examples below show it. Real executors
are here too: a task can shell out to any command (including a model CLI) or call a
model over the API. And it plans for you now: hand it a plain request and the control
loop turns it into a plan, runs it, checks each result, and writes a single answer.
What's still ahead (see the [roadmap](#roadmap)): a daemon to keep a fleet running.

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

To see the engine run a whole plan instead of just the ledger, there's a second
example:

```bash
python examples/run.py
```

It routes a request, runs a three-step plan across agents (with a stub standing in for
a real model), and verifies the entire run from the ledger at the end.

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

None of this is worth much if the record dies with the process. By default the
ledger lives in memory, which is right for a test or a single run. Point it at a
`FileStorage` instead and every entry is appended to a file and fsynced before the
next one, so the ledger survives a restart and still verifies, replays, and
checkpoints exactly. If a crash cuts the final write short, that half-written line
is dropped on reload and the rest of the record stands. Tampering does not get a
quieter treatment: a reordered file still loads, and `verify()` still says no.

## What's here

- `forum.ledger`: the record. Hash chain, content-addressed bodies, `verify` / `verify(deep=True)`, `replay`, `causal_chain`, Merkle `checkpoint`.
- `forum.storage`: where the record lives. An in-memory store for tests and short runs, and a durable `FileStorage` (append-only JSONL) so a ledger survives a restart and stays verifiable.
- `forum.routing`: a router that reads a request, picks a lane, and only falls back to a model when the keywords genuinely can't decide.
- `forum.plan`: a task graph compiled into parallel waves, with cycles and missing dependencies caught up front.
- `forum.roster`: the cast of specialists, written as plain data in a TOML file and validated on load. Ships with a built-in default roster of 24 plain capability lanes (`load_default()`), so a fresh install has a real roster out of the box.
- `forum.policy`: the rules of the room. Which work can run, and how much at once.
- `forum.executor` / `forum.api_executor`: how work actually runs. A stub for tests, a `SubprocessExecutor` that runs any command (point it at a model CLI), and an `ApiExecutor` that drives a model over the Anthropic API. A failing task is witnessed, not fatal.
- `forum.control` and `Orchestrator.submit`: the control loop. A Coordinator turns a plain request into a plan, a Classifier picks an agent when keywords can't, a Validator judges each result, and a Synthesizer writes one answer. Every step is witnessed.
- `forum.daemon` / `forum.http_surface`: an always-on HTTP service (stdlib asyncio, no framework) over one long-lived, durable ledger. Submit a request, read a witnessed answer, and verify or replay the record over HTTP.
- `forum.mcp_surface`: the same tools over MCP (JSON-RPC on stdio), the lone optional edge. It is a thin adapter over the HTTP surface, so the two can never drift.

Pure standard library. No third-party runtime dependencies. The tests run the
primitives directly, tamper detection and the Merkle property included.

## Roadmap

- **Done, the foundation.** Ledger, router, roster, planner, policy. Tested and runnable.
- **Done, the runtime.** An asyncio dispatcher that runs a plan's waves with bounded concurrency, a mailbox actor and a restart supervisor, and an Orchestrator that ties routing, planning, and witnessed dispatch into one call. The engine runs end to end against a stub executor today.
- **Done, real executors.** A `SubprocessExecutor` that runs any command (so any CLI, including a model CLI), and an `ApiExecutor` that drives a model over the Anthropic API, both behind the one executor seam. A failing task is witnessed, not fatal.
- **Done, the control loop.** A Coordinator that turns a plain request into a plan, a Classifier, a Validator that judges each result (a failed task is witnessed, not blessed), and a Synthesizer that writes one answer. `Orchestrator.submit` runs the whole loop, witnessed.
- **Done, durable storage.** A file-backed `FileStorage` (append-only JSONL) so a ledger outlives the process: it recovers exactly on restart, tolerates a crash-torn final write, and stays tamper-evident.
- **Done, the default roster.** 24 domain-neutral capability lanes (engineering, graphics, support, research) shipped in the box and loaded with `roster.load_default()`. Plain capability names, every lane keyword-routable.
- **Done, the daemon (HTTP).** A stdlib-asyncio HTTP service over one durable ledger: route, plan, submit, and verify or replay the record over HTTP. Every request witnessed into the same record.
- **Done, the MCP surface.** The same tools over MCP (JSON-RPC on stdio), a thin adapter over the HTTP surface so the two cannot drift. The lone optional edge.
- **Next.** A `forum` CLI and a published `pip install forum-engine` package.

## Design

[ARCHITECTURE.md](ARCHITECTURE.md) goes deeper on the layers and the ledger.

## License

Forum is fair-source: the code is open to read, run, and build on, with commercial
use reserved so the project can fund its own development. Copyright stays with the
author. See [LICENSE](LICENSE) for the exact terms.
