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

Durability is a dial, not a fixed cost. By default every append is fsynced before it
returns. When throughput matters more than the last few writes, `FileStorage(fsync_each=False)`
writes and flushes each append to the OS (so a process crash loses nothing) but defers
the fsync, and `ledger.sync()` fsyncs the logs on demand, at a phase boundary or the
run's end. Persistence past a power loss then rests on the OS honoring fsync (and the
parent directory entry is not separately synced), so the guarantee is scoped to that;
the process-crash guarantee is unconditional. Either way the log is still append-only, a
crash still only ever tears the final line, and whatever survived still verifies and replays.

## Routing

The router earns its place by not calling a model when it doesn't have to. It scores a
request against each lane by keyword, adjusted for how specific the lane is. If one
lane clears a confidence bar and beats the runner-up by a margin, it decides on the
spot. Ties break by a fixed order (score, then name), so the result never depends on
the order lanes happen to sit in the roster. Only when the keywords genuinely can't
separate the candidates does it escalate to the model-backed classifier above it.
Cheap and certain first, expensive and clever only when it's earned.

A route now carries a human frame as well as a lane. `forum.route_frame` derives a
deterministic `forum.route-frame/v1` payload from the request text and the route:
domain, intent, posture, delivery profile, selected model tier/executor,
proof/domain lane hints, a short human-facing answer contract, a nested
`forum.communication-contract/v1` payload, and the matched local signals. The
runtime fields are joined from the roster only when a route
decisively selects an agent; weak or escalated routes do not invent a model
policy. This is not semantic understanding and not a model judgment. It is a
local routing contract that tells the surfaces how the work should present
itself and what class of local runtime should handle it while preserving the old
route fields for compatibility. `Orchestrator.assign` witnesses the same frame
into the route entry, so future routing, delivery, and model-endpoint
improvements can train or evaluate against the exact contract the run carried.

## Roster, plan, policy

- Roster is a cast list, not code. Each specialist is a row in a TOML file (name, domain, keywords, model tier, executor), validated when it loads.
- Plan compiles a task graph into ordered waves you can run in parallel (Kahn's layering), and refuses anything with a cycle or a missing dependency up front. Its edges are typed: a data edge feeds the upstream's witnessed output into the downstream task so it builds on real work, while an order edge only sequences. Both constrain scheduling; the dispatcher records per task which upstreams it consumed (`data_from`), and the plan entry records every typed edge, so the data flow is in the ledger, not just the wiring. A task may also carry `done_when` criteria: the worker sees them in the task contract, the task entry witnesses them as structured data, and validation judges against the same criteria. Injected upstream output is capped so a deep plan cannot grow prompts without bound; the full output stays in the ledger, so only the prompt shrinks, not the record. A run is resumable from that record: re-dispatched with `resume=True` it reuses every task already witnessed as successful and re-runs only the rest, and it can checkpoint each wave as a re-checkable savepoint. The ledger is the resume state, so recovery reuses verified work rather than regenerating it with a model.
- Policy is the rule of the room: which categories of work may run, and how many at a time.

`forum.runtime.TieredExecutor` is the first executable consumer of that roster
policy. It wraps the existing executor seam and, for task agents that appear in
the roster, picks the configured cheap, capable, or frontier executor from the
agent's `model_tier`. Those tier executors can be shell commands or direct
OpenAI-compatible chat endpoints, so an operator can point cheap work at one
local server/model and frontier work at another without changing the plan shape.
`forum.runtime_config` is the durable local policy adapter for that same seam:
it reads a TOML file into the default executor and tier executor map, stores only
environment-variable names for bearer keys, and leaves explicit CLI flags as
one-run overrides. `forum.runtime_descriptor` and `forum.runtime_inspect` are
the read-only side of that boundary: they parse the same config and flags into
safe descriptors, join them to roster tier demand, and report default, tier,
fallback, or missing executor policy without running commands or touching model
endpoints. Control roles and unknown agents fall back to the default executor,
so the planner, validator, and synthesizer keep the same stable path unless the
operator chooses otherwise. The dispatcher asks an executor for the model id of
the specific assignment it is witnessing, so a wrapper can route internally
while the ledger still records `capable-local` or `frontier-local` on the task
result rather than a generic wrapper name.

## Surfaces

The daemon is the always-on edge. `forum.http_surface` is the HTTP semantics with
no sockets in it: a single `dispatch(method, path, body)` coroutine maps a request
to the Orchestrator and serializes JSON, so every endpoint is tested without a
network. `forum.daemon` is the transport, a hand-written HTTP/1.1 parser over
stdlib `asyncio.start_server` (no web framework), plus lifecycle: start, stop,
graceful drain, and a factory that gives the daemon one long-lived, durable
`FileStorage` ledger so every request witnesses into the same record. Routing and
the ledger are served without a model; planning and submitting drive the control
loop and need a model executor. Runtime inspection and context preflight are
read-only posture checks, so a host can inspect the live executor graph and
context pressure before it submits work. `forum.mcp_surface` is the same tools
over MCP (JSON-RPC on stdio), the lone optional edge adapter. It is a thin
wrapper over the very same HttpSurface, so the two surfaces can never drift: its
handle() seam is sockets-free and tested directly, and serve_stdio() wires real
streams.

## The run contract

A run is not just a loop; it carries a contract, witnessed like everything else. Before
planning, the Orchestrator asks a `ContextProvider` for organized context relevant to the
request. This is the seam to the "brain" (a peer like the index flagship can implement it);
the default provider returns nothing, so Forum stands alone. When context is supplied it is
witnessed as its own entry and the plan is chained to it, so the record shows the exact
context that shaped the work: request, then context, then plan.

Planned task contracts can be more precise than one instruction string. When the
Coordinator returns `done_when` criteria, Forum keeps the instruction and criteria
separate in the ledger while giving the worker a combined contract prompt. The
Validator receives that same contract, so a task's pass/fail verdict is tied to the
explicit stop condition the worker saw. This is the first layer below later human
approval checkpoints: concrete criteria first, approval gates later.

The same seam reaches every task. At dispatch each task pulls fresh, task-specific context
from the provider, capped like upstream data and witnessed as its own entry that the task is
chained to, so a parallel or looped agent gets up-to-date context routed to it and the record
shows what shaped each step. This is the Forum-native half of context management, and it keeps
the seam honest: Forum times, routes, and witnesses the context, but it never generates it.
The brain supplies it, the injection is verified (witnessed) and fresh (pulled per task), and
neither side is clever about timing. The pull is synchronous and runs once per task, so a brain
that does heavy I/O serializes the wave; it is meant to be fast and offline.

The context-pressure layer makes that budget explicit. A `ContextBudget` applies
model-agnostic approximate-token limits to request-level context, per-task context,
upstream data injection, and the task result inputs handed to final synthesis. Each
admitted, trimmed, or omitted slice is witnessed as `context_budget`; the normal
context entries store only admitted text, final synthesis receives a prompt-only copy
of admitted result text, and omitted text is represented by counts and a reason rather
than raw content. The original task result entries stay full-fidelity in the ledger.
`forum.context_preflight` is the read-only half of that mechanism: before submit,
it estimates request size and optional capsule context against the same
`ContextBudget` rules, reporting retained, trimmed, or omitted context without
writing ledger entries or copying raw capsule text into JSON.

Context Capsules make prior run state compact before it becomes context. The capsule
builder reads the ledger locally and extracts a deterministic brief: checkpoint,
verification state, latest request, latest answer, task outputs, and quality signals.
`LedgerCapsuleProvider` feeds that brief back through the same ContextProvider seam,
so a later run can use witnessed memory without raw ledger replay. If a ContextBudget
is configured, the capsule is admitted, trimmed, or omitted by the same request-context
path as any other provider output.

A `RunBudget` bounds the run. It caps model calls (deterministic, the cost-relevant
dimension) and, best-effort, wall-clock seconds. The call cap is checked as each task
starts, so a concurrent wave can overshoot it by at most the parallelism width. When the budget is spent the run stops
where it is, witnesses a `budget` entry, and still verifies and replays cleanly. A loop that
cannot run away, on context you can audit, is the difference between a demo and something you
would leave running.

Phase savepoints are available on the high-level submit path. With
`checkpoint_each_wave=True` (or `forum submit --checkpoint-each-wave`, or the same
HTTP/MCP field), the dispatcher witnesses a checkpoint after each execution wave and
syncs the ledger. The checkpoint format is the same one used by lower-level
`submit_plan`; the surface flag only makes it available to normal platform runs.

Model selection is witnessed too. Every result records the model that produced it,
including per-task selections made by `TieredExecutor`, and a task whose verdict
fails can escalate up a ladder of stronger executors. The escalation fires on the
witnessed verdict, an auditable signal, not on a model's self-reported confidence
(which a cascade attacker can game). Each retry and its verdict are recorded, so
the cheapest model that passes is chosen in the open rather than in a black box.

A completed run is also checked against the request that started it. Each task is
validated against its own instruction, but a run can pass every task and still answer a
different question than the one asked. So after synthesis the Orchestrator witnesses an
intent check: a deterministic, reproducible measure of how much of the request's
vocabulary the final answer carries, the terms it missed, and whether that falls below
a threshold. It is a lexical floor, not a semantic verdict; it records the signal and
never blocks the run, leaving what to do about drift to policy.

The rung above the floor is an opt-in model intent-judge. When the floor flags drift,
a model reads the request and the answer, is told which request terms the floor found
missing, and resolves whether the answer truly drifted or merely paraphrased. Its
verdict is witnessed and chained to the flag it resolves, it runs through the run's
executor, and it is bounded by the budget. The floor's known weakness is the
paraphrase: a correct answer that reuses few of the request's words flags anyway, and
the judge is what clears it. Cheap and certain first, the model only when the floor
earns it, the same discipline as routing and escalation.

The run's last word can come from outside. A VerifierProvider is the peer of the
ContextProvider: where context feeds organized knowledge in before the run, a verifier
checks the answer after it. A peer flagship, a proof-checker, or a test runner implements
the one-method seam, and Forum witnesses the verdict (verified, refuted, or
could-not-decide) as its own entry chained to the answer. The default abstains, so Forum
stands alone. Like the intent check it records the signal and does not block, leaving what
to do about a refuted answer to policy. The seam is synchronous, so a verifier that does
heavy work should keep it brief or offload it; a verifier that crashes is witnessed as
could-not-decide, never fatal, so external code can never sink an answer the run already
produced.

How the answer reads is checked too. A deterministic delivery floor (forum.delivery)
measures the answer's concision (sentence length, filler ratio) and flags one that is
dense or padded, witnessed every run. When it flags and a Reviser is configured, Forum
pulls a tighter version and accepts it only if it is strictly shorter and still covers
the request's terms (the same lexical coverage check the intent floor uses), so an
accepted revision drops no request term; that is a floor on dropped terms, not a proof
of preserved meaning. A revision that fails either test, or a reviser that crashes, is
recorded and discarded, and the original stands. The floor is the peer of the intent floor and the
reviser the peer of the verifier seam, and the default abstains. This is the verified
quality ladder applied to delivery: measure deterministically, let the model improve
only when the floor flags, and accept its work only when a check confirms it.

Expert Delivery Profiles add a second deterministic floor beside concision. A selected
profile (`operator`, `engineer`, `researcher`, or `executive`) checks the delivered
answer for model tells, indirect openings, filler, domain evidence language, and
profile-specific shape. The check is witnessed as `delivery_profile_check`; it does not
rewrite facts and it does not fail the run. It gives the operator a local, replayable
contract for how the answer was delivered.

Submit now connects routing and delivery by default. After the request entry is
witnessed, `Orchestrator.submit` derives and witnesses a `route_frame` entry for the
request. The frame's human and communication contracts are passed into the
synthesis prompt before the final answer is written. If the caller did not pass a delivery profile, the frame's
`delivery_profile` becomes the selected profile for the final answer check; an
explicit profile still wins. Submit receipts read those witnessed entries back and
report the route frame, the selected profile, and whether the selection came from the
route frame or the caller. The mechanism is deliberately local: Forum is not imitating
a named writer and not adding facts, it is selecting, prompting with, and checking a
prose contract that matches the work posture.

## Reading the record

A record you cannot read is only half of accountability. `forum.report` closes
that half without adding any trust. `summarize(ledger)` reads the ledger and
aggregates it into a run summary: counts by kind (requests, plans, tasks, results,
verdicts), task failures and verdict pass and fail, escalations, budget stops, the
model calls broken out per model, context-pressure checks and saved approximate tokens,
the Merkle checkpoint, and the verify result. It reads only what was witnessed and
re-derives nothing, so the summary is exactly as trustworthy as the ledger underneath
it, and it ships the checkpoint and verify flag alongside the numbers so a reader can
confirm that.

Run rooms are the operator read model over the same ledger. `forum.run_room` starts
from the latest request by default and projects that run into `forum.run-room/v1`:
request, route frame, plan waves, task contracts, latest results, verdicts,
checkpoints, answer, quality signals, deterministic `next_actions`, and a
`forum.run-room.brief/v1` operator brief. Those actions are advisory policy over
the witnessed state: retry failed tasks, raise a spent budget, resume from a
checkpoint, review delivery or verifier signals, judge intent drift, export a
receipt, or submit the first request when the room is empty. The brief is the
human readout over the same state: status, route posture, risk, next step, and a
few compact signals, all derived locally without asking a model to summarize the
ledger. This is not a second state store and not an invented narrative. It is a
clipped, structured view over witnessed entries, exposed through `forum ledger
room --json`, `forum ledger room --brief`, `GET /room`, and MCP `forum.run.room`
so UI and peer tools have a platform endpoint without learning every raw ledger
entry shape or reimplementing the same action derivation logic.

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
