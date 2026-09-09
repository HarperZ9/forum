# Validation cases

These cases define the public distribution checks for the Forum Route Preflight skill. They keep the workflow advisory and read-only. The checked distribution version is `forum-engine==1.13.0`; revalidate before claiming compatibility with any other Forum version.

## Unfinished-task intake

Task text:

```text
continue the unfinished native build recovery task: fix stale dirty-file drift, protect exported notes, and make the rescue checklist actionable
```

Observed with the tested 1.13.0 Forum distribution: `forum route --json` returned no decided lane, `needs_escalation: true`, tied low-confidence top candidates, and an implementation-oriented communication contract. Expected behavior for this skill: stop before dispatch and ask for or manually check the intended lane.

## Explicit frontend implementation route

Task text:

```text
frontend UI task: build a responsive React component with CSS layout and accessibility states
```

Observed with the tested 1.13.0 Forum distribution: the route selected `frontend` with confidence `1.0` and `needs_escalation: false`. Expected behavior: report the route and still inspect runtime before any submit.

## Wrong or ambiguous route control

Task text:

```text
native shader compiler database mobile cloud frontend backend docs gpu render pipeline model foundry route this work
```

Observed with the tested 1.13.0 Forum distribution: no lane was decided because many route candidates tied. Expected behavior: compare against the user's manual lane and treat ambiguity or disagreement as a stop condition. A lexical route is a routing hint, not semantic truth.

## Context overflow

Use a ledger capsule and small budget:

```bash
forum context preflight --json --use-capsule-context --ledger <FORUM_LEDGER> --context-token-budget 0 "continue the previous run"
```

Observed with a seeded ledger: `ready: false`, `context.action: omitted`, reason `max_total_tokens`. With a small nonzero budget, preflight reported `context.action: trimmed` and stayed ready with an issue. Expected behavior: omitted context blocks submit; trimmed context is allowed only if the user accepts the loss.

## Missing executor, no-execute default

Run runtime inspection only:

```bash
forum runtime inspect --json
```

Observed with no runtime options: runtime `ready: false` with missing executor state. Expected behavior: report missing executor and do not submit. The helper's default behavior must preserve this no-execute boundary and keep `decision.safe_to_submit: false`.

## Configured-ready helper seam

Run the helper with a sentinel command that would create a marker if executed:

```bash
python scripts/forum_route_preflight.py --cmd "<NON_EXECUTED_SENTINEL_COMMAND>" "frontend UI task: build a responsive React component with CSS layout and accessibility states"
```

Expected behavior: the helper passes `--cmd` to `forum runtime inspect --json`, runtime readiness becomes true, no marker is created, and `decision.safe_to_submit` remains false because the helper is advisory only.

## Invalid Forum source checkout

Run the helper with a nonexistent or non-Forum source path:

```bash
python scripts/forum_route_preflight.py --forum-repo <INVALID_FORUM_SOURCE_CHECKOUT> "frontend UI task: build a responsive React component with CSS layout and accessibility states"
```

Expected behavior: the helper returns a valid JSON receipt with `status: UNVERIFIABLE`, `invalid_forum_repo` in the decision reasons, no Python traceback, no raw source path, and no Forum command execution.

## Failed-command privacy control

Use a fake Forum package that exits nonzero while echoing its arguments, current working directory, and an environment variable selected through `--api-key-env`. Run the helper with private-looking task text, partial task text, ledger path, runtime config path, runtime command fragment, chat URL, model name, API-key environment variable name, and API-key environment variable value.

Expected behavior: the helper returns a valid JSON receipt with `status: UNVERIFIABLE`; failed-command `command` arrays replace task text with `<task-text>` and redact configured path, runtime command, chat URL, model, and API-key environment variable values; receipt sections do not include raw `stdout`, raw `stderr`, or `stdout_prefix`; diagnostics contain only per-stream byte counts and SHA-256 digests. None of the private task fragments, URLs, model names, environment names/values, command fragments, or paths appear anywhere in the receipt.

## Invalid-JSON privacy control

Use a fake Forum package that exits zero while printing non-JSON stdout and stderr containing the same private values used in the failed-command privacy control.

Expected behavior: the helper returns `forum_json_parse_failed` with `status: UNVERIFIABLE`, redacted command shape, exit code, and per-stream byte counts and SHA-256 digests only. The receipt does not include raw stdout/stderr text or any of the private values.

## MCP shape

Observed MCP `tools/list` for the tested Forum surface includes route, context preflight, and prose contract tools, with no per-lane specialist tools in the checked sample. Expected behavior: expose one workflow around these tools, not one wrapper per roster row.
