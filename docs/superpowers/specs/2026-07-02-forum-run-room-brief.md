# Forum Run-Room Brief Spec

Date: 2026-07-02

## Problem

`forum.run-room/v1` is useful as structured state, and `room_text` is useful for
debugging, but neither gives the operator a polished readout of the run. Forum
needs a deterministic brief that sounds like a platform reporting status: clear
state, posture, risk, and the next move, without asking a model to summarize the
ledger.

## Goals

- Add a deterministic `forum.run-room.brief/v1` object to every run-room payload.
- Capture run state as one of `idle`, `ready`, `in_progress`, `action_required`,
  or `complete`.
- Preserve human posture fields from the route frame when present.
- Surface risk in prose from witnessed signals only.
- Surface the primary next action in prose.
- Add a CLI `forum ledger room --brief` output mode.
- Keep existing JSON and `--text` behavior compatible.

## Non-Goals

- No model-generated summary.
- No new ledger entries; this is a read model over witnessed state.
- No mutation of next actions.
- No new HTTP path in this slice; HTTP and MCP receive the brief because they
  already expose the room JSON.

## Brief Shape

```json
{
  "schema": "forum.run-room.brief/v1",
  "state": "complete",
  "title": "Run complete: ship a login API",
  "posture": "architect",
  "delivery_profile": "engineer",
  "summary": "The latest run is verified, has a final answer, and has no blocking signals.",
  "risk": "No blocking signals detected.",
  "next_step": "Export run receipt.",
  "bullets": [
    "Route: implementation / execute / architect",
    "Tasks: 1 total, 1 with results, 1 accepted",
    "Answer: present"
  ]
}
```

## State Rules

- `idle`: no current request in the room.
- `action_required`: ledger verification failed, a high-priority next action is
  present, failed execution/validation signals exist, verifier refuted the run,
  intent or delivery profile is flagged, or budget stopped the run.
- `complete`: final answer present and no blocking signals exist.
- `in_progress`: tasks exist but final answer is not present.
- `ready`: request exists but no tasks are present yet.

## Acceptance Criteria

- `build_run_room` includes a `brief` object with schema, state, title, posture,
  risk, next step, and bullets.
- Complete runs produce complete-state prose and keep route posture/profile.
- Failed runs produce action-required prose and name the retry action.
- `room_brief_text(room)` emits a polished text brief.
- CLI `forum ledger room --brief` prints the brief without changing `--text` or
  JSON behavior.
