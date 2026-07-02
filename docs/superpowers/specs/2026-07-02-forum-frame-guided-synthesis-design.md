# Forum Frame-Guided Synthesis Design

## Purpose

Forum now derives a human route frame and uses it to choose the default delivery profile. The next step is to use the same frame before the final answer is written, so the model receives the posture contract up front instead of being checked only afterward.

This makes the delivery layer more architecturally human: the run sets the room, states the role posture, and gives the answer contract before synthesis.

## Current State

`Orchestrator.submit` derives and witnesses a `route_frame` entry after the request. It selects a delivery profile from that frame unless the caller explicitly overrides it. `Synthesizer.synthesize` currently receives only the request, task results, and executor; its prompt says only to combine results into one clear answer.

## Design

Extend `Synthesizer.synthesize` with an optional `delivery_contract` string parameter. When present, it inserts a compact `Delivery contract:` block into the final-answer prompt before `Write the final answer.`

`Orchestrator.submit` builds that contract from the witnessed route frame:

- posture;
- selected delivery profile;
- route intent and domain;
- human contract text.

The contract remains local and deterministic. It does not ask the model to imitate a person, a writer, or a brand voice. It tells the model which kind of expert posture the route already selected and what concrete answer qualities to satisfy.

## Behavior

- Existing direct calls to `Synthesizer().synthesize(request, results, executor)` remain valid.
- Submit calls pass a route-frame-derived contract into synthesis.
- The delivery profile check still runs after synthesis, so the prompt guidance is advisory while the ledger check remains the evidence.
- The route frame remains the witnessed record of the contract source; no new ledger entry is required for the first slice.

## Tests

Use TDD. Add tests before implementation for:

- direct `Synthesizer.synthesize(..., delivery_contract=...)` includes the contract in the prompt sent to the executor;
- direct `Synthesizer.synthesize(...)` without the parameter preserves the current prompt shape;
- `Orchestrator.submit` passes route-frame guidance into the synthesizer prompt for a model-foundry request.

## Documentation

Update README and architecture notes to say route frames now guide synthesis and then verify delivery through the existing delivery-profile check.

## Non-Goals

This does not add a new prompt template language, rewrite answer content locally, imitate named writers, or make the model's compliance trusted. The trusted part remains the witnessed route frame and delivery-profile check.
