# Forum Communication Contract Spec

Date: 2026-07-02

## Problem

Forum already derives a route frame with domain, intent, posture, delivery
profile, and a short human contract. That is enough to keep answers away from
generic model prose, but not enough for hosts, IDEs, or synthesis prompts to
share a detailed communication posture. The platform needs a deterministic
contract that says how an expert in the selected lane should lead, structure,
ground, and constrain the delivery.

## Goals

- Add a JSON-ready communication contract derived from route frame fields.
- Include the contract in route-frame payloads.
- Feed the contract into final-answer synthesis prompts.
- Expose the contract over HTTP and MCP for host tooling.
- Keep it deterministic, local, and model-free.

## Non-Goals

- No generated persona prose.
- No user-specific imitation.
- No model calls.
- No external style dependencies.
- No replacement of existing delivery profile checks.

## Payload Shape

```json
{
  "schema": "forum.communication-contract/v1",
  "domain": "implementation",
  "intent": "execute",
  "posture": "architect",
  "profile": "engineer",
  "lead": "Lead with the concrete change or decision.",
  "structure": ["change", "verification", "risk", "next step"],
  "evidence": ["name files, commands, tests, or ledger facts when available"],
  "avoid": ["model preambles", "vague optimism", "unsupported superlatives"],
  "required_moves": ["name the mechanism", "separate verified output from next work"]
}
```

## HTTP and MCP Shape

```http
POST /prose/contract
```

Body:

```json
{"text": "build the API endpoint", "profile": "engineer"}
```

MCP tool:

- `forum.prose.contract`

## Acceptance Criteria

- Route frames include `communication_contract`.
- Final-answer synthesis prompts include contract lead, structure, evidence,
  avoid, and required moves.
- `POST /prose/contract` routes the supplied text locally and returns the
  communication contract.
- MCP `tools/list` includes `forum.prose.contract`.
- MCP `forum.prose.contract` returns the same contract payload.
