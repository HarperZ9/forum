# Forum Human Routing Intelligence Design

## Purpose

Forum needs routing that feels like a senior operator setting up the work, not a keyword switchboard. The next slice builds a deterministic route frame that carries three things together:

- the work lane Forum should use,
- the communication posture the work deserves,
- the delivery profile that should shape the answer.

This moves Forum toward replacing orchestration harnesses by making every route carry a local, inspectable contract for action and communication before any model call happens.

## Current State

Forum already has a lexical router, a 28-lane roster, proof/domain lane vocabularies, vocabulary-gap receipts, context budgets, context capsules, and expert delivery profiles. The public `route` surfaces return a decided agent, confidence, escalation flag, and candidates. That is useful for dispatch, but it does not yet say what kind of engagement the work is, how the system should posture, or which delivery contract should shape the response.

The existing delivery profiles are answer-side checks. This design adds a request-side frame so the route can recommend the answer posture before the run starts.

## Design

Add a focused `forum.route_frame` module. It derives a `RouteFrame` from the request text and existing `RouteResult`.

The frame has these fields:

- `schema`: `forum.route-frame/v1`
- `agent`: the decided agent, or `null` when the route escalates
- `domain`: a broad work family such as `implementation`, `research`, `model-foundry`, `operator-platform`, `evidence`, or `general`
- `intent`: the action shape, such as `execute`, `investigate`, `design`, `validate`, `synthesize`, or `coordinate`
- `posture`: the communication stance, such as `operator`, `architect`, `investigator`, `reviewer`, or `teacher`
- `delivery_profile`: one of the existing delivery profiles: `operator`, `engineer`, `researcher`, or `executive`
- `proof_lane`: one of the closed proof lanes when it can be inferred: `observe`, `execute`, `validate`, `synthesize`, or `verify`
- `domain_lane`: one of the closed domain lanes when it can be inferred, otherwise `null`
- `human_contract`: a short local instruction for how the answer should present itself
- `signals`: matched local signals that explain why the frame was chosen

The frame is deterministic and zero-dependency. It does not replace the existing router. It wraps the route result with a richer contract that public surfaces can use in this slice and subsequent execution slices can consume through the same schema.

## Public Surface

The CLI `forum route`, HTTP `POST /route`, and MCP route tools should include a `frame` object beside the existing route fields. Existing fields stay unchanged for compatibility.

Example shape:

```json
{
  "decided": "model-foundry",
  "confidence": 0.625,
  "needs_escalation": false,
  "frame": {
    "schema": "forum.route-frame/v1",
    "agent": "model-foundry",
    "domain": "model-foundry",
    "intent": "validate",
    "posture": "architect",
    "delivery_profile": "engineer",
    "proof_lane": "validate",
    "domain_lane": "model-foundry",
    "human_contract": "Answer as a systems architect: name the mechanism, the gating evidence, and the next executable step.",
    "signals": ["eval", "promotion", "model", "daemon"]
  }
}
```

## Behavior

The first implementation should cover clear, high-value frames:

- model and daemon work becomes `model-foundry`, `architect`, `engineer`, with proof lane `validate` when eval or promotion language is present;
- browser, evidence, capture, source, and provenance work becomes `evidence`, `investigator`, `researcher`, with proof lane `observe` and domain lane `source-federation` where relevant;
- implementation work becomes `implementation`, `architect` or `operator`, `engineer`, with proof lane `execute`;
- review, audit, verification, and test work becomes `validate`, `reviewer`, `engineer`, with proof lane `validate` or `verify`;
- learning and explanation work becomes `teaching`, `teacher`, `researcher`, with proof lane `synthesize`;
- broad Project Telos or platform orchestration work becomes `operator-platform`, `operator`, `executive`, with proof lane `synthesize`.

When signals conflict, the frame should keep the router's decided agent, choose the strongest local posture signal, and include the matched signals so the output stays inspectable.

## Error Handling

Frame derivation should not throw for ordinary text. Empty or whitespace-only text is already rejected by HTTP route validation; direct module calls should still produce a general frame. Unknown agents or weak routes should use `general`, `coordinate`, `operator`, `operator`, and no proof/domain lane.

## Tests

Use TDD. Add tests before implementation for:

- pure frame derivation for model-foundry, evidence, implementation, validation, teaching, and weak/general requests;
- CLI route output includes the frame without removing existing fields;
- HTTP route output includes the same frame shape;
- MCP route inherits the HTTP route frame through the existing shared surface;
- `Orchestrator.assign` route ledger payloads include the route frame for future supervision data.

## Documentation

Update README and architecture notes to say routing now carries a human route frame: not just the target lane, but the posture and delivery contract. Keep the language precise: the frame is deterministic local architecture, not semantic understanding and not a model judgment.

## Non-Goals

This slice does not train a learned router, add a new model dependency, replace the lexical router, or force delivery profiles through every submit path. It creates the local route contract that future routing intelligence and expert delivery can consume.
