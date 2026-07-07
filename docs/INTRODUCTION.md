# An introduction to forum

forum is a zero-dependency Python engine for orchestrating fleets of agents. You hand
it a plain request. It routes the request to the right capability lane, plans it as a
dependency graph compiled into parallel waves, runs the waves across model-agnostic
executors, validates each result, and synthesizes one answer. The whole run, every
routing decision, task, result, and verdict, lands in a replayable causal ledger.

It runs three ways: as a Python library, as a `forum` command, and as an always-on
daemon that serves the same engine over HTTP and MCP. The core is pure standard
library, Python 3.11+, no third-party runtime dependencies.

## Why it exists

Most agent frameworks give you output and a log you are asked to trust. When a run
drifts, overspends, or fails at 3 a.m., the log cannot prove what happened or resume
what was lost. forum treats the record as the work: a hash-chained, content-addressed
ledger that a later run can verify, replay, resume from, and challenge.

## Core concepts

**The ledger.** An append-only record where every entry carries a fingerprint of the
one before it, and bulky bodies (prompts, outputs) are stored under a fingerprint of
their own bytes. `verify()` catches edits, drops, and reorders; `verify(deep=True)`
re-hashes each body and catches content tampering; `replay(until=...)` rebuilds any
past state; `causal_chain(seq)` answers why an entry happened; `checkpoint()` folds
history into one Merkle root. Backed by memory for tests, or a durable append-only
JSONL `FileStorage` that survives restarts and crash-torn writes.

**Routing and lanes.** A deterministic router reads a request and picks a lane from a
roster (28 domain-neutral capability lanes ship in the box), escalating to a model
classifier only when keywords genuinely cannot decide. Every route carries a
deterministic `forum.route-frame/v1` contract: domain, intent, posture, delivery
profile, selected runtime tier, and a communication contract that later shapes the
final answer. A separate closed lane vocabulary gates what scopes a route may claim,
and rejections are witnessed, never silently dropped.

**Plans and dispatch.** A task graph with typed edges (data edges feed witnessed
upstream output into downstream tasks; order edges only sequence) is compiled into
parallel waves, with cycles and missing dependencies caught up front. Tasks can carry
`done_when` criteria that workers see and validators judge. Runs checkpoint at wave
boundaries and resume from the ledger, reusing every task already witnessed as
successful.

**Executors.** How work actually runs, model-agnostic: any command via
`SubprocessExecutor` (a local model CLI needs no account), any OpenAI-compatible
server via `ChatExecutor`, or the Anthropic API via `ApiExecutor`. A `TieredExecutor`
routes task agents to cheap, capable, or frontier executors from roster policy. A
failed task is witnessed, not fatal, and can escalate up a ladder of stronger models.

**Budgets.** A `RunBudget` caps a run by model calls and wall clock, witnessing where
it stopped. A `ContextBudget` admits, trims, or omits request context, per-task
context, upstream injection, and synthesis inputs under approximate-token caps, every
decision witnessed. `forum context preflight` estimates the pressure before the run.

**Quality gates.** After synthesis, a deterministic coverage check flags answers that
drift from the request, with an opt-in model judge to resolve flags. A concision floor
flags verbose answers; an opt-in reviser tightens them, accepted only if the shorter
version still covers the request. Expert delivery profiles (`operator`, `engineer`,
`researcher`, `executive`) check the final answer against a local prose contract.

**Approval gates.** A `GatePolicy` pauses a run at a wave boundary until an operator
approves, edits, or rejects it (`forum gate list / approve / edit / reject`). A gate
can carry a durable deadline with a witnessed auto-decision on expiry, evaluated only
on resume, so nothing runs behind the operator's back. See
[GATE-DEADLINES.md](GATE-DEADLINES.md).

**Campaigns.** A campaign declares multiple projects' features as a JSON dependency
graph. `forum campaign run` dispatches the runnable features to a fixed point,
`campaign status` reduces the ledger into current state, `campaign next` derives the
next operator actions, and `campaign ingest-status` records external progress without
executing anything.

**Seams.** Two provider interfaces keep forum composable: a `ContextProvider` supplies
organized context (fresh per task, capped, witnessed), and a `VerifierProvider` lets
an external checker judge the answer after the run. Both default to no-ops, so forum
stands alone.

## Your first ten minutes

Install it:

```bash
pip install forum-engine
```

See routing and the ledger with no model at all:

```bash
forum route "build the auth endpoint and the database schema"
```

It answers with a decided lane (`backend`), a confidence, and the route frame. Then
clone the repo and run the demo, which plans and runs a small graph, tampers with a
stored result, and shows the deep verify catching it:

```bash
git clone https://github.com/HarperZ9/forum
cd forum
python examples/demo.py
```

Now run a real request end to end. Any local model CLI works; with
[Ollama](https://ollama.com) installed:

```bash
forum submit "ship a login API" --cmd "ollama run llama3"
```

forum routes the request, plans it, runs the tasks, validates each result, and prints
one synthesized answer. Read the record it left behind:

```bash
forum ledger show --limit 20      # the witnessed entries
forum ledger verify               # chain and payload integrity
forum ledger summary              # counts, model calls, verdicts, weight
forum ledger room --brief         # operator brief: state, risk, next step
```

Prefer an HTTP endpoint or an MCP host? The same engine serves both:

```bash
forum serve --chat-url http://localhost:11434/v1/chat/completions --model llama3
forum mcp --cmd "ollama run llama3"
```

Add `--json` to `submit` to get an action receipt joining the answer to ledger
sequence, payload hash, model identity, checkpoint, and verification verdict.

## Where to go next

- [../RUNNING.md](../RUNNING.md): real-model setups, tiered executors, runtime TOML.
- [../USAGE.md](../USAGE.md): the operator command surface.
- [../ARCHITECTURE.md](../ARCHITECTURE.md): the layers and how they compose.
- [GATE-DEADLINES.md](GATE-DEADLINES.md): human-in-the-loop gates in depth.
- [ENTERPRISE-READINESS.md](ENTERPRISE-READINESS.md): receipts, envelopes, host-neutral operation.
- [../examples/](../examples/): one short, offline script per capability.
- [../CHANGELOG.md](../CHANGELOG.md): what shipped in each release and what is on main.
