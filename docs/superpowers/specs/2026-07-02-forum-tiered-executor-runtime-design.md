# Forum Tiered Executor Runtime Design

## Purpose

Forum now exposes route-frame runtime policy (`model_tier` and `executor`) from
the roster. The next step is to make that policy executable locally. A platform
runtime should be able to send cheap lanes to a cheap local model, capable lanes
to a stronger local model, and frontier lanes to a frontier local model without
changing the orchestration API.

This slice adds a tier-aware executor wrapper and CLI tier command flags.

## Current State

`Orchestrator` and `dispatch_plan` accept one executor. The roster records
`model_tier`, route frames expose it, and result entries witness a model id, but
task execution still goes through the same executor for every agent.

## Design

Add `forum.runtime.TieredExecutor`:

- wraps the existing executor seam;
- receives a `Roster`, a default executor, and optional tier executors keyed by
  `cheap`, `capable`, and `frontier`;
- selects a tier executor from `roster.by_name(assignment.agent).model_tier`;
- falls back to the default executor for control roles (`coordinator`,
  `validator`, `synthesizer`, `intent-judge`) and unknown agents;
- exposes `model_id_for(assignment)` so ledger result entries can witness the
  actual selected runtime instead of only the wrapper name.

Add `assignment_model_id(executor, assignment)` beside `executor_id`. Existing
executors keep their current behavior; only executors that implement
`model_id_for` get assignment-aware attribution.

Add CLI flags:

- `--cheap-cmd`;
- `--capable-cmd`;
- `--frontier-cmd`.

When any tier command is present, `_make_executor` returns a `TieredExecutor`.
`--cmd` remains the base/control executor. If no base executor is supplied, the
first configured tier in `capable`, `frontier`, `cheap` order becomes the default
for control calls and unknown agents. That keeps local-only setups usable while
preserving the old single-executor path.

## Behavior

- A backend task in the default roster selects the capable executor.
- A technical-writing task selects the cheap executor.
- A model-foundry task selects the frontier executor.
- Unknown/control agents fall back to the default executor.
- `dispatch_plan` result payloads record the selected executor's model id per
  task.
- Existing `--cmd`, `--chat-url`, and `--api` behavior remains unchanged when no
  tier flags are used.

## Tests

Use TDD. Add tests before implementation for:

- `TieredExecutor` selecting cheap/capable/frontier/default executors from the
  roster;
- `dispatch_plan` witnessing per-task selected model ids;
- CLI tier flags parsing and wrapping a base executor;
- CLI tier flags working without `--cmd` by choosing a configured tier as the
  default.

## Documentation

Update README and architecture notes to describe tiered local runtime selection
as the first executable consumer of route-frame runtime policy.

## Non-Goals

This does not add endpoint health checks, config files, model downloads,
OpenAI-compatible tier URL flags, scheduler learning, cost telemetry, or dynamic
model promotion. Those belong after the deterministic runtime selector exists.
