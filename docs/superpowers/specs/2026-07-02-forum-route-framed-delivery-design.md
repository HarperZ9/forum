# Forum Route-Framed Expert Delivery Design

## Purpose

Forum now derives a human route frame for each route. The next delivery step is to let that frame shape a run by default, so Forum answers like the kind of expert the work calls for without requiring the operator to pass a delivery profile manually.

The result should feel less like a generic model response and more like a local execution layer that sets the room, picks the posture, and checks the delivered answer against that posture.

## Current State

`forum.route_frame` produces a deterministic `forum.route-frame/v1` payload with `posture`, `delivery_profile`, and `human_contract`. `Orchestrator.submit` already accepts an explicit `delivery_profile`, validates it early, and witnesses a `delivery_profile_check` after the final answer. If no explicit profile is passed, no expert profile check runs.

That means the new request-side frame is visible in route output, but not yet used in full runs.

## Design

At the beginning of `Orchestrator.submit`, after the request is witnessed, Forum derives a route frame for the request text using the existing router. It writes that frame as a `route_frame` ledger entry chained to the request.

Delivery profile selection becomes:

1. If the caller supplied `delivery_profile`, use it and record source `explicit`.
2. Otherwise use `route_frame.delivery_profile` and record source `route_frame`.

The selected profile is then used by the existing `delivery_profile_check` mechanism. This means every normal submit gets an expert delivery check, while explicit caller intent still overrides the automatic frame.

Receipts should expose the selection:

- requested profile, if any;
- selected profile;
- selection source: `explicit`, `route_frame`, or `none`;
- observed delivery profile check counts;
- route frame schema, domain, intent, posture, delivery profile, proof lane, domain lane, and human contract.

## Public Surface

No new flags are required. Existing CLI, HTTP, and MCP submit calls inherit route-framed delivery automatically. Existing `--delivery-profile` and `delivery_profile` fields keep their meaning and override the frame.

`forum submit --json`, HTTP `POST /submit`, and MCP `forum.submit` receipts should include enough detail to show whether the profile came from the route frame or from the caller.

## Behavior

- Model-foundry requests default to the `engineer` profile and architect posture.
- Evidence requests default to the `researcher` profile and investigator posture.
- Broad operator-platform requests default to the `executive` profile and operator posture.
- Weak/general requests default to the `operator` profile.
- Unknown explicit profiles still fail before running the model.
- The route frame is witnessed even if later planning or execution fails after the request has been accepted.

## Error Handling

Route-frame derivation should not add new failure modes to submit. If route-frame derivation cannot classify the text strongly, the general operator frame is used. If a frame ever names an unknown delivery profile, `get_profile` should raise and the run should fail before additional model work, because an invalid local contract is a programmer error.

## Tests

Use TDD. Add tests before implementation for:

- `Orchestrator.submit` without an explicit profile witnesses `route_frame` and `delivery_profile_check`;
- the selected profile comes from the frame when no explicit profile is passed;
- explicit `delivery_profile` overrides the frame-selected profile;
- CLI/HTTP/MCP submit receipts expose route-frame and profile-selection fields;
- unknown explicit profiles still fail before ledger writes beyond the request boundary already covered by existing tests.

## Documentation

Update README and architecture notes to explain that routing now influences delivery by default. Keep the language exact: Forum is not copying a writer's style, claiming authorship, or adding facts. It is selecting a local prose contract and checking for concrete delivery qualities.

## Non-Goals

This slice does not rewrite the answer using the route frame, train a style model, imitate specific living writers, or add a new model dependency. It makes the current deterministic delivery profile system automatic, witnessed, and receipt-visible.
