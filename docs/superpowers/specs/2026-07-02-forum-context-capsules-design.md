# Forum Context Capsules Design

## Purpose

Forum already limits context pressure by trimming or omitting oversized context. The
next step is not only to spend fewer tokens, but to carry useful run state forward in
a compact, local, replayable form. Context Capsules are deterministic briefs derived
from the ledger. They let a later run receive the smallest useful memory of what
happened before without asking a model to summarize the whole ledger.

This directly supports the larger goal: Forum should replace orchestration harnesses
by treating state, memory, receipts, and communication as local architecture, not as
more raw model context.

## Design Alternatives

### Approach A: Model-Written Summaries

After each run, call a model to summarize the ledger into a prompt. This can produce
polished prose, but it spends another model call, inherits hallucination risk, and
creates a summary that is less trustworthy than the ledger it claims to explain.

### Approach B: Raw Ledger Replay as Context

Feed prior ledger entries back into the next run. This is faithful, but it is exactly
the token-management failure mode the feature is meant to solve. It also leaks low-value
control chatter into the next model prompt.

### Approach C: Deterministic Ledger Capsule

Read the ledger locally and extract only compact, typed facts: latest request, latest
answer, task statuses, failed verdicts, verification state, delivery flags, context
pressure metrics, and checkpoint. Render the capsule as JSON for machines and as a
plain text brief for a ContextProvider. This is the recommended approach.

## Chosen Architecture

Add `forum.context_capsule`, a pure module that reads a `Ledger` and produces a
`ContextCapsule` payload with schema `forum.context-capsule/v1`.

The capsule has two public shapes:

- `build_context_capsule(ledger, *, max_items=8, max_text_chars=240) -> dict`
  returns a JSON-ready capsule payload.
- `capsule_text(capsule: dict) -> str` renders a compact prompt-safe brief.

A small `LedgerCapsuleProvider` implements the existing `ContextProvider` seam by
calling those functions. That makes capsules usable as request context without
changing `Orchestrator.submit` or the dispatcher.

## Capsule Content

The capsule should include:

- `schema`
- `checkpoint`
- `verified`
- `entry_range`
- `counts` for key ledger kinds
- `latest_request`
- `latest_answer`
- `tasks`, capped to the last `max_items`, each with id, agent, ok, model, and clipped output
- `signals`, including failed verdicts, refuted verifications, flagged intent checks,
  delivery flags, delivery profile flags, context tokens saved, and budget stops
- `context_text_chars`, the rendered brief length

No raw payload larger than `max_text_chars` is copied into the capsule. Long strings
are clipped deterministically with a suffix marker.

## Public Surfaces

Expose capsules where operators and hosts already inspect ledgers:

- CLI: `forum ledger capsule --ledger DIR --json` emits the JSON payload.
- CLI: `forum ledger capsule --ledger DIR --text` emits the rendered brief.
- CLI: `forum submit ... --use-capsule-context` uses the current ledger capsule as
  request context before planning.
- HTTP: `GET /capsule` returns the JSON payload for the daemon ledger.
- MCP: `forum.ledger.capsule` returns the same JSON payload.

The submit flag composes with existing context budgets. If both `--use-capsule-context`
and context budget flags are present, the capsule is treated as request context and
goes through the same `ContextBudget` admission path.

## Error Handling

An empty ledger returns a valid capsule with empty request, answer, tasks, and signals.
Missing payload bodies are skipped rather than fatal; the capsule reports only material
that can be read from the content store. Invalid CLI flag combinations should return
the existing parser error shape.

## Testing

Tests must prove:

- Capsule JSON is deterministic and contains the latest request, answer, checkpoint,
  task details, and signal counts.
- Rendered capsule text is compact and includes request, answer, checkpoint, and
  critical signals.
- `LedgerCapsuleProvider.context()` returns the rendered capsule.
- CLI, HTTP, and MCP expose capsules.
- `forum submit --use-capsule-context` witnesses a `context` entry derived from the
  prior capsule and still works with context budgets.

## Non-Goals

This feature does not create semantic summaries, embeddings, vector retrieval, or
ranked long-term memory. It is the deterministic local layer those systems can build
on later.

## Self-Review

- No unfinished markers remain.
- The feature is a single bounded subsystem: deterministic ledger compaction and
  surface exposure.
- The design keeps raw model summarization out of scope and uses existing seams.
- The submit integration is opt-in and composes with current context budgets.
