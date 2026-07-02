# Forum Synthesis Result Budget Design

## Purpose

Forum already budgets request context, per-task context, and dependency output injected into downstream task prompts. The final synthesis stage is still an unbounded prompt surface: every task result is joined into the synthesizer prompt in full.

This slice budgets task result text before final synthesis, without rewriting or deleting the witnessed task result entries. The goal is prompt pressure control at the last model call while keeping the ledger as the complete record of what happened.

## Current State

`dispatch_plan` applies `ContextBudget` to:

- request context before planning;
- task context before each task runs;
- upstream dependency output injected into downstream task prompts.

`Orchestrator.submit` then calls:

```python
await self.synthesizer.synthesize(request, results, counter, delivery_contract=...)
```

The `results` dictionary is the full witnessed output map. If a run produced large outputs, the synthesizer receives them all, even when `ContextBudget(max_upstream_tokens=...)` was supplied.

## Design

Add a prompt-only budgeting step inside `Orchestrator.submit` immediately before synthesis:

1. If no `context_budget` is supplied, preserve current behavior and pass `results` unchanged.
2. If `context_budget` is supplied, build a new `dict[str, Result]`.
3. For each successful or failed result, call `apply_context_budget("upstream", f"{task_id}->synthesizer", result.output, context_budget, context_meter)`.
4. Witness every non-empty pressure record as `kind="context_budget"`, parented to the result entry when available.
5. Replace only the prompt copy with `dataclasses.replace(result, output=admitted_output)`.
6. Pass the prompt copy into `Synthesizer.synthesize`.

This reuses the existing `ContextBudgetMeter`, so `max_total_tokens` is global across request context, task context, inter-task upstream context, and final synthesis inputs.

## Behavior

- Full task outputs remain in their original `result` ledger entries.
- The synthesizer prompt receives admitted slices only.
- Trimmed synthesis inputs use the existing `ContextBudget` source `upstream` with labels like `T1->synthesizer`.
- Receipts and reports include synthesis-stage budget pressure automatically because they already summarize all `context_budget` entries.
- The final answer remains witnessed as before.

## Tests

Use TDD. Add a submit-level test that:

- runs a scripted task returning a large output;
- supplies `ContextBudget(max_upstream_tokens=2)`;
- asserts the synthesizer prompt contains the admitted slice, not the full output;
- asserts the original result ledger entry still stores the full output;
- asserts a `context_budget` entry exists for `T1->synthesizer` with `action="trimmed"`.

Add a receipt-level assertion where useful through existing receipt tests, not a broad surface rewrite.

## Documentation

Update README and architecture notes so token management is described as end-to-end prompt pressure control across request context, per-task context, dependency injection, and final synthesis.

## Non-Goals

This does not introduce semantic summarization, retrieval ranking, learned compression, cache eviction, or a new budget schema. It is a deterministic budget application over the existing context-budget mechanism.
