# Forum Submit Wave Checkpoints Design

## Purpose

Forum's dispatcher can already witness a checkpoint after each execution wave, but the primary `submit` path does not expose that capability. Operators using CLI, HTTP, or MCP must drop to `submit_plan` to get phase savepoints.

This slice exposes per-wave checkpoints through the high-level submit path. It strengthens Forum as a platform execution layer because normal planned runs can leave resumable, auditable phase boundaries without special Python API usage.

## Current State

`dispatch_plan(..., checkpoint_each_wave=True)` appends `kind="checkpoint"` entries after each wave and syncs the ledger. `Orchestrator.submit_plan` exposes this flag. `Orchestrator.submit`, `forum submit`, `POST /submit`, and MCP `submit` do not.

## Design

Add `checkpoint_each_wave: bool = False` to `Orchestrator.submit`.

Pass the flag into `dispatch_plan` when the generated plan runs.

Expose the same boolean through:

- CLI: `forum submit --checkpoint-each-wave`;
- HTTP: JSON field `"checkpoint_each_wave": true`;
- MCP: `checkpoint_each_wave` in `submit` and `forum.submit` input schemas and request bodies.

Receipts do not need a new schema field in this slice. They already report the ledger range, entry count, checkpoint root, and verification status. Ledger summaries already count checkpoint entries.

## Behavior

- Default submit behavior is unchanged.
- When enabled, one checkpoint entry is witnessed per plan wave.
- Checkpoints are causal children of the plan entry because the dispatcher owns wave execution.
- HTTP rejects non-boolean `checkpoint_each_wave` values with a 400 response.
- MCP forwards the boolean to HTTP, keeping the surfaces aligned.

## Tests

Use TDD. Add tests before implementation for:

- `Orchestrator.submit(..., checkpoint_each_wave=True)` producing checkpoint entries for a multi-wave plan;
- CLI argument parsing for `--checkpoint-each-wave`;
- HTTP `POST /submit` producing checkpoint entries when the JSON field is true and rejecting non-booleans;
- MCP `forum.submit` forwarding the boolean and producing checkpoint entries.

## Documentation

Update README and architecture notes to say high-level submit runs can now leave per-wave phase savepoints.

## Non-Goals

This does not add approval gates, pause/resume UX, checkpoint signing, or a new receipt schema. Those are later platform-room features built on top of checkpoint entries.
