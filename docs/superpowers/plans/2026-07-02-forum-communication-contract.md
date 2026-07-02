# Forum Communication Contract Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:test-driven-development before implementation and
> superpowers:verification-before-completion before claiming completion.

**Goal:** Add deterministic, route-derived communication contracts that make
Forum's domain posture and delivery expectations explicit to synthesis and host
tools.

**Architecture:** Create a pure `communication_contract` module. Route frames
will embed its payload, synthesis will append its text representation to the
delivery contract, and HTTP/MCP will expose a model-free contract endpoint over
the same route semantics.

## Global Constraints

- No model calls.
- No user-specific imitation.
- Preserve existing route frame fields.
- Keep MCP mapped through HTTP.
- Keep profile validation through existing delivery profiles.

## Tasks

- [ ] Add failing unit tests for the communication contract payload and text.
- [ ] Add failing route-frame payload tests.
- [ ] Add failing synthesis prompt contract tests.
- [ ] Add failing HTTP and MCP contract surface tests.
- [ ] Implement `forum.communication_contract`.
- [ ] Wire route frame, synthesis, HTTP, and MCP.
- [ ] Run targeted tests, Ruff, full suite, staged checks, and commit.
