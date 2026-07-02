# Forum Run Room Snapshot Design

## Purpose

Forum has a durable ledger, summaries, receipts, and context capsules. Those are useful but they answer different questions. A platform execution layer also needs a room view: the current state of the run in one structured payload, shaped for an operator or peer tool that needs to inspect the work without manually replaying raw entries.

This slice adds a read-only `forum.run-room/v1` snapshot. It makes Forum feel less like a low-level harness and more like an execution platform: request, route, plan, task contracts, results, verdicts, checkpoints, answer, and quality signals are available as one room.

## Current State

- `forum.report.summarize` gives aggregate counts.
- `forum.context_capsule.build_context_capsule` gives compact memory for model context.
- Submit receipts give action-level verification for one submit call.
- Raw ledger replay gives full fidelity but requires callers to understand every entry shape.

There is no operator-facing room payload that joins these into the latest run state.

## Design

Create `src/forum/run_room.py` with:

- `RUN_ROOM_SCHEMA = "forum.run-room/v1"`;
- `build_run_room(ledger: Ledger, *, since_seq: int | None = None, max_text_chars: int = 240) -> dict`;
- `room_text(room: dict) -> str` for prompt-safe/operator-readable text.

When `since_seq` is omitted, the room begins at the latest `kind="request"` entry. This keeps durable multi-run ledgers focused on the active room by default. If there is no request, the room covers the whole ledger.

The payload includes:

- checkpoint and verification state;
- entry range and counts for the room;
- latest request entry with clipped text;
- latest route frame;
- latest plan waves and edges;
- task list from `kind="task"` entries, joined with latest result and verdict by task id;
- checkpoint entries;
- latest answer;
- quality signals from budget, delivery, intent, and verification entries.

All long text is clipped with the same convention as context capsules. Full content stays in the ledger.

## Surfaces

Expose the room through existing inspection surfaces:

- CLI: `forum ledger room --json` and default JSON output;
- HTTP: `GET /room`;
- MCP: `forum.run.room`.

The MCP tool routes through HTTP so it does not drift.

## Behavior

- The room is read-only and never appends ledger entries.
- It does not replace receipts, summaries, capsules, or replay.
- It uses existing ledger payloads and tolerates missing optional entries.
- `max_text_chars` must be non-negative.
- Latest-run filtering is based on request sequence, not on inferred task ids.

## Tests

Use TDD. Add tests before implementation for:

- pure room payload extraction from a ledger with request, route frame, plan, done criteria, result, verdict, checkpoint, answer, and signals;
- latest-request filtering across a multi-run ledger;
- CLI `ledger room --json`;
- HTTP `GET /room`;
- MCP `forum.run.room`.

## Documentation

Update README and architecture notes to describe run rooms as the operator/platform read model over the witnessed ledger.

## Non-Goals

This does not add a browser UI, websocket streaming, approval gates, room persistence separate from the ledger, or model-generated summaries. It is the structured read model those later features can use.
