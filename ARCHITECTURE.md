# Architecture

One idea runs through the whole codebase: the record is the source of truth. Not a
log kept on the side, but the work itself. Every routing decision, plan, and result
is an entry in a ledger you can check. Hold onto that sentence and the rest of the
design reads as a series of consequences.

## What this actually solves

A language model is brilliant and forgetful. Each call starts blank, and the only
thing it leaves behind is whatever you wrote down. So if you want to build a
dependable system on one, something you can debug, audit, and trust under load, you
have to supply the two faculties the model can't provide for itself:

- durable contact with state, a memory that outlives any single conversation;
- verified contact, a memory you can check rather than one you hope is honest.

Add the reach to act across many agents at once, and you have the shape of the
project. The pieces below are how those get built.

## The layers

```
surfaces (HTTP / MCP daemon)                                   [next]
        |
control loop (classify, coordinate, validate, synthesize)      [next]
        |
core primitives:  routing . roster . plan . policy . ledger    [here today]
        |
executors (Claude Code subagent . API . CLI)                   [next, edge adapters]
```

The core stays pure on purpose. No I/O, no clock except one you pass in, no
third-party imports. Anything that touches the outside world, the executors that call
models, the surfaces that take requests, the storage that holds a ledger, lives at
the edge as an adapter. The payoff is that the logic worth thinking about stays small
enough to keep in your head and reproducible enough to test exactly.

## The ledger

It's an append-only hash chain joined to a content-addressed store, and the two
halves do different jobs.

The chain is the tamper-evidence. Each entry commits to its own fields (seq, ts,
actor, kind, causal_parent, payload_hash, prev_hash) and folds in the hash of the
entry before it. Change a past entry, delete one, or reorder them, and the
fingerprints disagree. `verify()` walks the chain and reports the first place the
record and reality split.

The store holds the bulky bodies, the prompts and outputs, keyed by the hash of their
own bytes. That keeps the chain compact, and it buys a quieter feature: you can redact
a sensitive body to its key alone and the chain still verifies. When bodies are
present, `verify(deep=True)` re-derives each one's hash and compares, which is how a
swapped result gets caught even when the chain links cleanly.

The rest follows.

- `causal_chain(seq)` follows the causal_parent links to rebuild the path that led to an entry. The answer to "why did this happen."
- `replay(until=seq)` rebuilds exact past state, which is only possible because the core is pure and entries are immutable.
- `checkpoint()` folds the history into one Merkle root. Leaves are tagged 0x00 and internal nodes 0x01, and a lone odd node is carried up rather than duplicated. That's the standard defense against the second-preimage collision (CVE-2012-2459) that naive Merkle code walks into.

## Storage

The ledger keeps its logic and its persistence apart. A `Storage` is a small
protocol (append an entry, read them back, fetch or stash a payload by its hash),
and the core only ever talks to that protocol, never to a file. `InMemoryStorage`
is the default, right for tests and a single run. `FileStorage` is the durable
adapter: two append-only JSONL logs in a directory, one for entries and one for
content-addressed payloads, read back into memory on construction. Every append is
flushed and fsynced before the in-memory mirror is updated, so disk is the source
of truth and a restart recovers the exact ledger.

Durability and tamper-evidence do not fight here. A crash can only ever cut the
final line short, so on reload a torn trailing line is dropped and the rest of the
record stands; interior corruption, a structurally broken row, raises rather than
limps on. Tampering is left visible on purpose: a reordered or edited file still
loads, and `verify()` reports it false, exactly as it would in memory. Whole-tail
truncation is the one thing a lone append-only log cannot self-detect, which is
what `checkpoint()` and an external witness are for.

## Routing

The router earns its place by not calling a model when it doesn't have to. It scores a
request against each lane by keyword, adjusted for how specific the lane is. If one
lane clears a confidence bar and beats the runner-up by a margin, it decides on the
spot. Ties break by a fixed order (score, then name), so the result never depends on
the order lanes happen to sit in the roster. Only when the keywords genuinely can't
separate the candidates does it escalate to the model-backed classifier above it.
Cheap and certain first, expensive and clever only when it's earned.

## Roster, plan, policy

- Roster is a cast list, not code. Each specialist is a row in a TOML file (name, domain, keywords, model tier, executor), validated when it loads.
- Plan compiles a task graph into ordered waves you can run in parallel (Kahn's layering), and refuses anything with a cycle or a missing dependency up front.
- Policy is the rule of the room: which categories of work may run, and how many at a time.

## Surfaces

The daemon is the always-on edge. `forum.http_surface` is the HTTP semantics with
no sockets in it: a single `dispatch(method, path, body)` coroutine maps a request
to the Orchestrator and serializes JSON, so every endpoint is tested without a
network. `forum.daemon` is the transport, a hand-written HTTP/1.1 parser over
stdlib `asyncio.start_server` (no web framework), plus lifecycle: start, stop,
graceful drain, and a factory that gives the daemon one long-lived, durable
`FileStorage` ledger so every request witnesses into the same record. Routing and
the ledger are served without a model; planning and submitting drive the control
loop and need a model executor. `forum.mcp_surface` is the same tools over MCP
(JSON-RPC on stdio), the lone optional edge adapter. It is a thin wrapper over
the very same HttpSurface, so the two surfaces can never drift: its handle()
seam is sockets-free and tested directly, and serve_stdio() wires real streams.

## The run contract

A run is not just a loop; it carries a contract, witnessed like everything else. Before
planning, the Orchestrator asks a `ContextProvider` for organized context relevant to the
request. This is the seam to the "brain" (a peer like the index flagship can implement it);
the default provider returns nothing, so Forum stands alone. When context is supplied it is
witnessed as its own entry and the plan is chained to it, so the record shows the exact
context that shaped the work: request, then context, then plan.

A `RunBudget` bounds the run. It caps model calls (deterministic, the cost-relevant
dimension) and, best-effort, wall-clock seconds. The call cap is checked as each task
starts, so a concurrent wave can overshoot it by at most the parallelism width. When the budget is spent the run stops
where it is, witnesses a `budget` entry, and still verifies and replays cleanly. A loop that
cannot run away, on context you can audit, is the difference between a demo and something you
would leave running.

Model selection is witnessed too. Every result records the model that produced it, and a
task whose verdict fails can escalate up a ladder of stronger executors. The escalation
fires on the witnessed verdict, an auditable signal, not on a model's self-reported
confidence (which a cascade attacker can game). Each retry and its verdict are recorded,
so the cheapest model that passes is chosen in the open rather than in a black box.

## Reading the record

A record you cannot read is only half of accountability. `forum.report` closes
that half without adding any trust. `summarize(ledger)` reads the ledger and
aggregates it into a run summary: counts by kind (requests, plans, tasks, results,
verdicts), task failures and verdict pass and fail, escalations, budget stops, the
model calls broken out per model, the Merkle checkpoint, and the verify result. It
reads only what was witnessed and re-derives nothing, so the summary is exactly as
trustworthy as the ledger underneath it, and it ships the checkpoint and verify flag
alongside the numbers so a reader can confirm that.

`compare(a, b)` takes two such summaries and reports the delta on the numeric
fields, and `forum bench A B` runs it over two ledgers. This is the measurement
seam for the project's own improvement: a change that claims to cut model calls or
failures is held to the record of two runs rather than a recollection. Both
functions are pure and read-only, the same discipline as the core they read.

## Determinism

Nothing in the core reads the wall clock or rolls dice in a way that changes its
output. The clock is something you hand in. That one rule is what lets the tests
assert exact hashes, waves, and verdicts instead of vague shapes, and it's the same
property that makes replay trustworthy. A system that promises to reconstruct the past
has to be deterministic, or the promise is empty.
