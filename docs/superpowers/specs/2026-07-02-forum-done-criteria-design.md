# Forum Done Criteria Design

## Purpose

Forum can already stop a runaway run through `RunBudget`, and it can validate task outputs after they run. What it does not yet have is a first-class success contract for a planned task. A task has an instruction, but no separate, witnessable statement of what "done" means.

This slice adds optional task-level done criteria. The feature gives Forum a more advanced execution posture: every worker can receive explicit success criteria, the ledger can preserve those criteria as structured data, and validation can judge against the same contract.

## Current State

`Task` contains:

- `id`;
- `agent`;
- `instruction`;
- dependencies;
- order-only dependency metadata.

The Coordinator prompt asks for `id`, `agent`, `instruction`, and `depends_on`. Dispatch witnesses task entries with the original instruction and data inputs. Validation receives only the instruction string.

## Design

Add `done_when: tuple[str, ...] = ()` to `Task` as the final dataclass field so existing positional constructors stay valid.

Add a `Task.contract_instruction()` helper that returns:

```text
<instruction>

Done criteria:
- <criterion 1>
- <criterion 2>
```

when criteria are present, and the plain instruction otherwise.

Coordinator behavior:

- Update the planner prompt to allow an optional `done_when` list.
- Parse `done_when` from model JSON as a list of strings.
- Preserve older model output with no `done_when` as an empty tuple.

Dispatch behavior:

- Send `task.contract_instruction()` to the worker before adding upstream or task context.
- Keep the witnessed `instruction` field as the original task instruction.
- Add a structured `done_when` field to the task ledger payload only when criteria are present.

Validation behavior:

- Pass `task.contract_instruction()` into `_witness_verdict` for planned submit runs.
- Escalation retries inherit the same criteria through the dispatcher prompt helper.
- `submit_one` remains unchanged because it is a single raw task without a planner-produced criteria list.

## Behavior

- Existing task constructors and old coordinator JSON remain compatible.
- Done criteria are not trusted because the model wrote them; they are a contract the run carries, witnesses, and checks.
- Criteria do not create a human approval gate in this slice.
- Criteria do not replace validators, verifiers, route frames, or delivery profiles. They strengthen the task-level contract.

## Tests

Use TDD. Add tests before implementation for:

- `Task.contract_instruction()` formatting with and without criteria;
- `Coordinator` parsing optional `done_when`;
- dispatcher worker prompts including criteria while ledger task payloads keep original instruction and structured criteria;
- `Orchestrator.submit` validation prompts including criteria from the planned task.

## Documentation

Update README and architecture notes to describe done criteria as explicit task stop contracts and as a foundation for later human approval checkpoints.

## Non-Goals

This does not add approval checkpoints, UI pause/resume, policy enforcement by criteria, or semantic decomposition of vague criteria. Those belong in later slices once the criteria are present in the plan and ledger.
