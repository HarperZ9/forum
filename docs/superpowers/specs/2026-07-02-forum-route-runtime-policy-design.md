# Forum Route Runtime Policy Design

## Purpose

Forum already treats capability lanes as data. The default roster records each
agent's abstract `model_tier` and `executor`, but the route frame that drives
operator communication and submit receipts does not expose that runtime policy.

This slice makes the route frame carry the local runtime contract for the
selected lane. It is a small but important step toward a local model platform:
surfaces can see not just who should work, but what class of local model or
executor should be used.

## Current State

`forum.route_frame/v1` includes:

- selected agent;
- domain and intent;
- posture and delivery profile;
- proof/domain lane hints;
- human-facing answer contract;
- matched local signals.

The roster already has `model_tier` (`cheap`, `capable`, or `frontier`) and
`executor` (`cli` today), but callers must re-open the roster and join it
manually.

## Design

Add optional fields to `RouteFrame` and `frame_payload`:

- `model_tier`: the selected agent's roster tier, or `None` when no agent is
  decided;
- `executor`: the selected agent's roster executor key, or `None` when no agent
  is decided.

`derive_route_frame(text, route, roster=None)` remains backwards-compatible. When
no roster is supplied, the fields are `None`. Production callers that already
have a roster pass it in:

- CLI `forum route`;
- HTTP `POST /route`;
- `Orchestrator.submit`;
- `Orchestrator.assign`.

Because route frames are witnessed into the ledger, submit receipts and run rooms
inherit the runtime policy without new receipt or room plumbing.

## Behavior

- Decided backend implementation routes expose `model_tier="capable"` and
  `executor="cli"`.
- Decided model-foundry routes expose `model_tier="frontier"` and
  `executor="cli"`.
- Weak/escalated routes expose `None` for both fields.
- Existing route-frame clients remain compatible because the schema gains
  optional fields.

## Tests

Use TDD. Add tests before implementation for:

- route-frame helper with a decided backend route exposing runtime policy;
- weak route exposing no runtime policy;
- HTTP route response including runtime policy;
- submit/run-room ledger route frame preserving runtime policy.

## Documentation

Update README and architecture notes to describe route frames as carrying a
local runtime policy as well as a human delivery contract.

## Non-Goals

This does not implement a multi-executor registry, automatic model endpoint
selection, model downloads, or dynamic tier promotion. It exposes the contract
those later features can consume.
