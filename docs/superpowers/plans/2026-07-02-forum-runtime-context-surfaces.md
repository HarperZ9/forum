# Forum Runtime and Context Surface Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:test-driven-development before implementation and
> superpowers:verification-before-completion before claiming completion.

**Goal:** Make runtime inspection and context preflight callable from the
running Forum HTTP and MCP surfaces.

**Architecture:** Add a runtime descriptor path for live executor instances,
then wire HTTP endpoints over `inspect_runtime` and `build_context_preflight`.
Keep MCP as a thin route map over those HTTP endpoints.

## Global Constraints

- No model calls or command execution during runtime inspection.
- Do not output secret values; env var names are acceptable.
- Preflight must not write ledger entries.
- MCP and HTTP must share payload behavior.

## Tasks

- [ ] Add failing HTTP and MCP tests for runtime and context preflight.
- [ ] Add live executor descriptor support.
- [ ] Add `GET /runtime`.
- [ ] Add `POST /context/preflight`.
- [ ] Add MCP route aliases and tool schemas.
- [ ] Run targeted tests and lint checks.
- [ ] Inspect diff, run staged whitespace and focused secret checks, then
  commit the slice.
