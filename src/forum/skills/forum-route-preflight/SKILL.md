---
name: forum-route-preflight
description: Use Forum route preview, context preflight, runtime inspection, and prose contracts before continuing, decomposing, or dispatching agent work. Do not use for automatic execution or per-specialist wrappers.
metadata:
  short-description: Preview Forum routing before agent execution
---

# Forum Route Preflight

Use this when a user asks to continue, recover, hand off, route, or decompose work and Forum is available as a local CLI, Python package, or MCP server. The skill gives a deterministic pre-dispatch check; it does not run work, install hooks, approve gates, or turn Forum's roster into separate specialist tools.

## What this protects

Forum's route is lexical and deterministic. It is useful before a model call because it exposes the selected lane, confidence, escalation flag, model tier, proof lane, and communication contract. It is not a competence proof. If `needs_escalation` is true, if the selected lane conflicts with the user's stated/manual lane, if context preflight is not ready, or if runtime inspection shows no executor, stop before `forum submit` and report the blocker.

## Requirements

- Tested with `forum-engine==1.13.0`, or a Forum source checkout with `src/forum` available at the same API level.
- Re-run this skill's validation cases before using a different Forum version for distribution or host installation.
- Python 3.11+.
- No model, network, account, or credentials are needed for route preview, prose contract, context preflight, or runtime inspection.
- Execution requires separate user intent and a configured Forum executor. Do not call `forum submit`, `forum serve`, install a global hook, or approve a gate from this skill alone.

## Workflow

1. Verify Forum availability with `forum --version` or source checkout equivalent `python -m forum --version`.
2. Run route preview: `forum route --json "<task>"`.
3. Compare the route to any user-stated or manually selected lane. A mismatch is a finding, not permission to auto-correct and dispatch.
4. Run context preflight before injecting a ledger capsule or memory: `forum context preflight --json "<task>"`, adding `--use-capsule-context --ledger <ledger>` when a Forum ledger exists.
5. Get the prose contract through MCP `forum.prose.contract` when MCP is configured, or with the bundled helper script in this skill.
6. Run runtime inspection: `forum runtime inspect --json`. Runtime inspection may receive configuration options such as `--cmd`, `--chat-url`, `--api`, or `--runtime-config`; this inspection must not execute the configured command.
7. Present a compact decision: route, confidence, escalation, context action, runtime readiness, communication contract, and the next safe step.

## Optional helper

Use `scripts/forum_route_preflight.py` when you want one local read-only receipt instead of manually running the separate commands. It shells out to Forum's existing CLI for route, context preflight, and runtime inspection, and derives the communication contract from Forum's package modules. It never calls submit.

Install the tested distribution in an isolated environment before distribution validation:

```bash
python -m pip install forum-engine==1.13.0
```

Run against an installed Forum package:

```bash
python scripts/forum_route_preflight.py \
  --manual-lane frontend \
  "frontend UI task: build a responsive React component with CSS layout and accessibility states"
```

Run against a source checkout, using placeholders instead of operator-local paths:

```bash
python scripts/forum_route_preflight.py \
  --forum-repo <FORUM_SOURCE_CHECKOUT> \
  --use-capsule-context --ledger <FORUM_LEDGER> \
  --context-token-budget 4000 \
  "continue the previous run from its capsule"
```

Check configured-runtime readiness without executing the command:

```bash
python scripts/forum_route_preflight.py \
  --cmd "<MODEL_EXECUTOR_COMMAND>" \
  "frontend UI task: build a responsive React component with CSS layout and accessibility states"
```

The helper receipt is `forum-route-preflight.receipt/v2`. It records only a SHA-256 hash of the task text at the top level. For failed Forum subprocesses and invalid JSON output, it does not include subprocess stdout or stderr text. It records the redacted command shape, exit code when a process ran, and per-stream diagnostic metadata: byte count and SHA-256 digest of the raw stdout/stderr bytes. The helper also scrubs exact path, runtime command, chat URL, model, API-key environment variable name inputs, and the current environment value for any supplied API-key environment variable name from parsed successful JSON before printing the shareable receipt. Raw diagnostic capture is not part of this public helper; add it only as a separate explicitly selected local artifact feature.

Read [references/validation-cases.md](references/validation-cases.md) before changing this skill or claiming the workflow is ready in another host.

## Compatibility limits

- Forum's default roster contains routeable capability lanes, not independent executable tools for every roster row.
- `forum.prose.contract` is available through MCP/HTTP and package modules; the Forum CLI does not expose it as a standalone subcommand in 1.13.0.
- Context preflight only tests injected context or ledger capsule pressure. A long request without context is reported as request size, not as omitted context.
- Route preview may surface ambiguous input, such as "native continuation," as `needs_escalation=true`; do not dispatch on the top candidate in that case.
- This skill does not grant permission for network calls, model calls, global hook installation, social posting, release publishing, or production deployment.


