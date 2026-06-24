# Architecture

One idea organizes this whole codebase: **the record is the source of truth.** Not a
log written alongside the work, but the work itself — every routing decision, plan,
and result is an entry in a ledger that can be checked. If you keep that one sentence
in mind, the rest of the design reads as a series of consequences.

## What problem this actually solves

A language model is brilliant and amnesiac. Each call begins with a blank slate, and
the only thing it leaves behind is whatever you choose to write down. So if you want
to build a dependable system on top of one — a system you can debug, audit, and
trust under load — you have to supply the two faculties the model has no way to
provide for itself:

- **durable contact with state** — a memory that outlives any single conversation;
- **verified contact** — a memory you can *check*, rather than one you hope is honest.

Add the **range** to act across many agents at once, and you have the shape of the
whole project. The pieces below are how those faculties get built, brick by brick.

## The layers

```
surfaces (HTTP / MCP daemon)                                   -- next
        |
control loop (classify -> coordinate -> validate -> synthesize) -- next
        |
core primitives:  routing . roster . plan . policy . ledger    <-- here today
        |
executors (Claude Code subagent . API . CLI)                   -- next (edge adapters)
```

The core stays deliberately pure: no I/O, no clock except one you hand it, no
third-party imports. Everything that touches the outside world — the executors that
call models, the surfaces that take requests, the storage that persists a ledger —
lives at the edges as an adapter. The payoff is that the interesting logic is small
enough to hold in your head and reproducible enough to test exactly.

## The ledger, in depth

It is an append-only hash chain married to a content-addressed store, and the two
halves do different jobs.

The **chain** is the tamper-evidence. Each entry commits to its own fields —
`seq, ts, actor, kind, causal_parent, payload_hash, prev_hash` — and folds in the
hash of the entry before it. Alter a past entry, delete one, or reorder them, and the
fingerprints stop agreeing. `verify()` walks the chain and reports the first place
reality and record diverge.

The **store** holds the bulky bodies — prompts, outputs — keyed by the hash of their
own bytes. That keeps the chain compact, and it buys a quieter virtue: you can redact
a sensitive body down to its key alone, and the chain still verifies. When bodies are
present, `verify(deep=True)` re-derives each one's hash and compares, which is how a
swapped result gets caught even though the chain links cleanly.

Everything else is a consequence of those two:

- **`causal_chain(seq)`** follows the `causal_parent` links to reconstruct the path that led to an entry — the answer to *why did this happen?*
- **`replay(until=seq)`** rebuilds exact past state, which is only possible because the core is pure and entries are immutable.
- **`checkpoint()`** folds the history into a single Merkle root. Leaves are tagged `0x00` and internal nodes `0x01`, and a lone odd node is promoted rather than duplicated — the standard defense against the second-preimage collision (CVE-2012-2459) that naive Merkle code walks straight into.

## Routing

The router earns its keep by *not* calling a model when it doesn't need to. It scores
a request against each capability lane by keyword, normalized for how specific the
lane is, and if one lane clears a confidence bar and beats the runner-up by a margin,
it decides on the spot. Ties break by a fixed order — score, then name — so the
outcome never depends on the order lanes happen to appear in the roster. Only when the
keywords genuinely can't separate the candidates does it escalate to the model-backed
classifier above it. Cheap and certain first; expensive and clever only when earned.

## Roster, plan, policy

- **Roster** is a cast list, not code. Each specialist is a row in a TOML file — name, domain, keywords, model tier, executor — validated when it loads.
- **Plan** compiles a task graph into ordered waves you can run in parallel (Kahn's layering), refusing up front anything with a cycle or a missing dependency.
- **Policy** is the rule of the room: which categories of work may run, and how many at a time.

## Determinism, and why it matters here

Nothing in the core reads the wall clock or rolls dice in a way that changes its
output; the clock is something you pass in. That single constraint is what lets the
tests assert *exact* hashes, waves, and verdicts rather than vague shapes — and it is
the same property that makes `replay` trustworthy. A system that promises to
reconstruct the past has to be deterministic, or the promise is empty.
