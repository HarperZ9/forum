# Architecture

Forum is built so the **record is the source of truth**. Everything an orchestrator
does — routing a request, planning dependencies, dispatching work, recording a
result — is an event appended to a witnessed ledger. Verification and replay are
first-class, not bolted on.

## The thesis

A language model is stateless and context-bounded. To build reliable systems on top
of one, you need two things it doesn't have on its own:

- **durable contact with state** — a record that outlives any single context window;
- **verified contact** — that record has to be checkable, not taken on faith.

Forum provides both for a fleet of specialist agents, plus the **range** to act
across many of them. v0.1 is the substrate: the ledger and the routing / planning
primitives.

## Layers

```
surfaces (HTTP / MCP daemon)                                   -- roadmap
        |
control loop (classify -> coordinate -> validate -> synthesize) -- roadmap
        |
core primitives:  routing . roster . plan . policy . ledger    <-- v0.1 (this release)
        |
executors (Claude Code subagent . API . CLI)                   -- roadmap (edge adapters)
```

The core is pure: no I/O, no clock except an injected one, no third-party imports.
Everything that touches the outside world — executors, surfaces, persistence — is an
adapter at the edge, so the core stays small and fully testable.

## The ledger

An append-only hash chain with a content-addressed payload store.

Each entry commits to `seq, ts, actor, kind, causal_parent, payload_hash, prev_hash`,
and its `entry_hash` chains to the previous entry. So:

- **`verify()`** recomputes the chain and catches any mutation, reorder, or gap.
- **`verify(deep=True)`** additionally re-hashes each stored payload body against its content key; an absent (redacted / hash-only) payload is allowed and skipped.
- Payloads are content-addressed, so the chain stays compact and sensitive bodies can be stored hash-only without breaking integrity.
- **`causal_parent`** makes the ledger a causal graph: `causal_chain(seq)` reconstructs the decision path behind any entry.
- **`replay(until=seq)`** reconstructs exact past state — deterministic, because the core is pure and entries are immutable.
- **`checkpoint()`** is a Merkle root over the entry hashes, domain-separated (leaves tagged `0x00`, internal nodes `0x01`) with odd nodes promoted rather than duplicated, so two different histories cannot collide (CVE-2012-2459).

## Routing

Deterministic first. A keyword index scores a request against each capability lane,
normalized by lane specificity. If one lane clears a confidence threshold and beats
the runner-up by a margin, it is decided; otherwise the router escalates (a
model-backed classifier is the next layer up). Ties break by a total order (score,
then name), so the result never depends on roster declaration order. No model is
called for the easy cases.

## Roster, plan, policy

- **Roster** is data, not code: capability lanes are rows in a TOML manifest (name, category, domain, keywords, model tier, executor), validated on load.
- **Plan** turns a task DAG into ordered parallel waves (Kahn layering), detecting cycles and unknown dependencies.
- **Policy** gates which categories may run and caps how many tasks run in parallel.

## Determinism and testing

Clocks are injected; nothing in the core reads the wall clock or uses randomness in
a way that affects output. That makes the whole core reproducible, which is why the
tests can assert exact hashes, waves, and verdicts. The 29 tests cover the primitives
directly — including tamper detection and the Merkle collision-resistance property.
