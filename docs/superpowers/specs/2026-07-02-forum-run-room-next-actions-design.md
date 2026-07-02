# Forum Run Room Next Actions Design

## Purpose

Run rooms now collect the latest run state into one operator-facing payload. The next step is to make that room actionable. A platform execution layer should not force each UI, MCP client, or peer tool to infer what to do from raw signals. Forum can derive deterministic next actions from the witnessed room state.

This slice adds a `next_actions` list to `forum.run-room/v1`.

## Current State

`build_run_room` returns:

- request;
- route frame;
- plan;
- tasks with latest result and verdict;
- checkpoints;
- answer;
- quality signals.

Callers can inspect those fields, but they have to write their own logic to decide whether the next move is retry, judge intent, review verification, revise delivery, resume from checkpoint, or export the receipt.

## Design

Add deterministic action derivation inside `forum.run_room`.

Each action is a dict:

```json
{
  "id": "retry-task:T1",
  "kind": "retry_task",
  "priority": "high",
  "label": "Retry T1",
  "reason": "latest task result failed",
  "target": {"task_id": "T1", "result_seq": 4}
}
```

Initial action kinds:

- `submit_request`: empty room, no request yet.
- `retry_task`: latest task result failed or latest verdict failed.
- `raise_budget`: run stopped on budget.
- `resume_from_checkpoint`: checkpoint exists but no answer exists.
- `revise_delivery`: delivery floor or profile flagged.
- `judge_intent`: intent floor flagged.
- `review_verification`: external verifier refuted the answer.
- `export_receipt`: answer exists and no blocking signal needs attention.

Actions are ordered by priority and deterministic insertion order. High-priority corrective actions come before normal export actions. The list is advisory; Forum does not execute actions from the room builder.

## Behavior

- `build_run_room` always includes `next_actions`.
- The room remains read-only and appends no ledger entries.
- Repeated signals should not create duplicate retry actions for the same task.
- Long labels are not generated from raw model output, so no text clipping is required inside actions.
- HTTP, CLI, and MCP receive the field automatically because they already expose the room payload.

## Tests

Use TDD. Add tests before implementation for:

- a clean answered room producing an `export_receipt` action;
- failed task or failed verdict producing `retry_task`;
- flagged intent, refuted verification, and delivery flags producing their corresponding actions;
- checkpoint without answer producing `resume_from_checkpoint`.

## Documentation

Update README and architecture notes to describe run rooms as actionable operator rooms.

## Non-Goals

This does not add an action executor, retry endpoint, approval UI, websocket stream, or policy automation. It only makes next action intent explicit and portable.
