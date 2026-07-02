# Forum Context Preflight Spec

Date: 2026-07-02

## Problem

Forum witnesses context trimming during a run, but the operator cannot inspect
context pressure before starting that run. For a local execution layer trying to
outperform raw frontier-model calls by architecture, context has to become a
planned resource: visible, bounded, and predictable before the model receives it.

## Goals

- Add a deterministic context preflight payload.
- Estimate request tokens using Forum's existing approximate-token rule.
- Optionally build the current ledger capsule and test it against request-context
  budget limits before submit.
- Report configured limits, context action, original/admitted/saved tokens, and
  issues.
- Add a CLI surface for JSON and text output.
- Avoid printing raw capsule text in JSON.

## Non-Goals

- No model tokenizers or provider-specific token counts.
- No model calls.
- No mutation of the ledger.
- No automatic budget recommendations yet.

## CLI Shape

```bash
forum context preflight "ship a login API" --json
forum context preflight "ship a login API" --use-capsule-context --ledger forum-ledger --request-context-token-budget 80
```

## Payload Shape

```json
{
  "schema": "forum.context-preflight/v1",
  "ready": true,
  "request": {"tokens": 5, "bytes": 18},
  "context": {
    "source": "capsule",
    "action": "trimmed",
    "reason": "max_request_tokens",
    "original_tokens": 120,
    "admitted_tokens": 80,
    "tokens_saved": 40
  },
  "limits": {"bytes_per_token": 4, "max_request_tokens": 80},
  "issues": ["capsule context would be trimmed before planning"]
}
```

## Rules

- `ready` is false only when requested context would be omitted entirely.
- A trimmed context is usable but gets an issue so the operator sees the pressure.
- Empty or absent context is reported as `source: "none"` and `action: "none"`.
- JSON does not include raw request context or capsule text; it reports counts.
- Text mode may name the request token count and action, but it does not print the
  capsule body.

## Acceptance Criteria

- `build_context_preflight` reports request byte/token counts.
- Capsule context is tested with the same `ContextBudget` logic used by submit.
- Omitted capsule context marks `ready: false` and reports an issue.
- CLI `forum context preflight TEXT --json` emits the payload.
- CLI text mode is concise and readable.
