# Forum Runtime and Context Surface Spec

Date: 2026-07-02

## Problem

Forum now has local runtime inspection and context preflight builders, but those
capabilities are only usable through CLI paths. If Forum is going to become the
Project Telos platform and execution layer, IDEs, plugins, and local harnesses
need to ask the running Forum surface what executor policy is active and whether
context will fit before submitting work.

## Goals

- Expose runtime inspection through HTTP and MCP.
- Expose context preflight through HTTP and MCP.
- Reuse the same pure payload builders as the CLI surfaces.
- Keep MCP as an adapter over HTTP so transports do not drift.
- Avoid model calls, network probes, command execution, or secret output.
- Allow preflight to include the current ledger capsule without returning raw
  capsule text.

## Non-Goals

- No executor health probing.
- No automatic context budget tuning.
- No provider-specific tokenizers.
- No mutation of ledger entries during preflight.
- No changes to submit behavior.

## HTTP Shape

```http
GET /runtime
POST /context/preflight
```

The context preflight body accepts:

```json
{
  "request": "continue the current run",
  "use_capsule_context": true,
  "max_items": 8,
  "max_text_chars": 240,
  "context_token_budget": 0
}
```

## MCP Shape

- `forum.runtime.inspect`
- `forum.context.preflight`

Both tools return JSON text content using the same payloads as HTTP.

## Acceptance Criteria

- `GET /runtime` returns `forum.runtime.inspect/v1` for the current
  orchestrator executor.
- `POST /context/preflight` returns `forum.context-preflight/v1` and supports
  the same context budget fields as submit.
- Capsule-backed preflight can be requested and omitted context marks
  `ready: false`.
- MCP `tools/list` includes the two prefixed Project Telos tools.
- MCP calls for both tools return the HTTP payloads with `isError: false` for
  valid requests.
