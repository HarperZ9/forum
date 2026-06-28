# Forum Enterprise Readiness

Forum is the enterprise orchestration edge: it routes agent work, records progress in an append-only ledger, injects bounded context, and verifies whether the run stayed on task.

This guide aligns the flagship with Project Telos context envelopes and action receipts. The goal is unattended agent work that can be left running and later inspected: what context the agent saw, what exact material it relied on, what it changed, what verified, and what remained unverifiable.

## Enterprise Role

- Route requests into capability lanes without model calls when deterministic routing is enough.
- Record requests, plans, tasks, results, context injections, verifications, delivery checks, and budget stops in a replayable ledger.
- Humanize agent prose without adding facts, preserving the difference between readability and evidence.

## Host Commands

- `forum status --json` and `forum doctor --json` for host readiness.
- `forum route TEXT` before dispatching a worker.
- `forum submit TEXT --max-model-calls N --max-seconds S` for bounded runs.
- `forum ledger verify` and `forum ledger summary --json` for replay and audit.
- `forum mcp` for stdio MCP hosts.

## Context Envelope Contribution

- Context envelopes should join to the route, plan, task, and context-injection ledger entries that shaped the run.
- Large workspaces should enter Forum as bounded task-specific context from Index, not as whole-repo prompt dumps.
- Humanized prose is an output transform; it must not become new evidence unless Gather or Crucible witnesses it separately.

## Action Receipt Contribution

- Action receipts should join to ledger sequence, causal parent, payload hash, model identity, budget state, and verification entry.
- Compensation is append-only: a correction or rollback is a new ledger event with a pointer to the action it compensates.
- Typed stop reasons include budget spent, verifier abstained, policy denied, task failed, and user interruption.

## Readability Gate

Enterprise agent output should be easier for the next agent and a human reviewer to continue:

- Keep patches small enough to review and tied to one bounded work item.
- Prefer named helpers and domain terms over dense inline logic.
- Preserve public interfaces unless the receipt explains why they moved.
- Leave tests, command output, changed files, and next action in the handoff.
- Mark missing source refs, stale packets, failed tests, and verifier abstentions as UNVERIFIABLE instead of guessing.

## Platform Boundary

The flagship remains usable alone through CLI JSON and as part of a larger surface through MCP. OpenAI, Anthropic, IDE, CLI, TUI, and application hosts should consume the same tool outputs and receipt fields rather than reimplementing flagship behavior.

See Project Telos `project-telos.context-envelope/v1` and `project-telos.action-receipt/v1` for the shared cross-tool contract.
