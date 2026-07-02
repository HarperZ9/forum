from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable

from forum.context import ContextProvider
from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    ContextPressure,
    apply_context_budget,
    pressure_payload,
)
from forum.executor import Assignment, Executor, Result, executor_id
from forum.ledger import Ledger
from forum.plan import Plan, Task

# Per-upstream cap on injected output, to bound prompt growth down a deep or wide
# plan. Generous enough to leave normal outputs untouched; only runaway gets trimmed.
DEFAULT_MAX_UPSTREAM_CHARS = 8192


def augment_with_upstream(
    task: Task, results: dict[str, Result], *, max_chars: int = DEFAULT_MAX_UPSTREAM_CHARS
) -> tuple[str, list[str]]:
    """Feed a task's data-dependency outputs into its instruction.

    Returns ``(instruction_for_the_executor, the upstream ids actually injected)``. A
    data edge feeds the upstream's witnessed output into the downstream task so it can
    build on real work; an order edge only sequences and injects nothing. A failed
    upstream (ok=False) is not injected: the engine never treats a failure as usable
    work, so a downstream is not handed an error as build-on material, and the returned
    data_from lists only upstreams actually consumed. A data edge whose upstream failed
    thus appears in the plan's edges but not in the downstream's data_from; that
    divergence is a witnessed signal, not a bug.

    Each upstream output is capped at ``max_chars`` to bound prompt growth: an output
    over the cap is injected truncated with a marker, while the full output stays in the
    upstream's witnessed result entry, so the record loses nothing and only the prompt
    shrinks. Safe to call on concurrent tasks within a wave: no await (so it runs
    atomically between scheduling points) and it reads only the results of strictly
    earlier waves, which the wave barrier guarantees are complete. Deterministic:
    upstreams are injected in depends_on order, deduplicated.
    """
    parts: list[str] = []
    data_from: list[str] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is not None and up.ok and dep not in data_from:
            output = up.output
            if len(output) > max_chars:
                omitted = len(output) - max_chars
                output = output[:max_chars] + f"\n... [truncated for prompt efficiency, {omitted} chars omitted; full output is witnessed]"
            parts.append(f"- {dep}: {output}")
            data_from.append(dep)
    instruction = task.contract_instruction()
    if not parts:
        return instruction, []
    return instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from


def augment_with_upstream_budgeted(
    task: Task,
    results: dict[str, Result],
    *,
    context_budget: ContextBudget,
    context_meter: ContextBudgetMeter,
) -> tuple[str, list[str], list[ContextPressure]]:
    parts: list[str] = []
    data_from: list[str] = []
    pressures: list[ContextPressure] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is None or not up.ok or dep in data_from:
            continue
        output, pressure = apply_context_budget(
            "upstream", f"{dep}->{task.id}", up.output, context_budget, context_meter
        )
        pressures.append(pressure)
        if not output:
            continue
        if pressure.action == "trimmed":
            omitted = pressure.original_bytes - pressure.admitted_bytes
            output = output + (
                f"\n... [truncated for prompt efficiency, {omitted} bytes omitted; "
                "full output is witnessed]"
            )
        parts.append(f"- {dep}: {output}")
        data_from.append(dep)
    instruction = task.contract_instruction()
    if not parts:
        return instruction, [], pressures
    return instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from, pressures


def _completed_results(ledger: Ledger, ids: set[str]) -> dict[str, tuple[str, int]]:
    """Map each task id with a witnessed successful result to (output, that result's seq).

    Reads the durable ledger so a resumed run can reuse work already done. The latest
    ok=True result per id wins (seq order). Only successful results are reused; a task
    with no result, or only a failed one, is left to run again. No model is involved:
    resume reuses the verified record, it does not regenerate it.

    Resume assumes one ledger directory holds a single run lineage: task ids are matched
    across all prior entries, so do not resume a plan over a ledger populated by an
    unrelated plan that reuses the same ids.
    """
    done: dict[str, tuple[str, int]] = {}
    for e in ledger.query(kind="result"):
        body = ledger.get_payload(e.payload_hash)
        tid = body.get("id")
        if tid in ids and body.get("ok") is True:
            done[tid] = (body["output"], e.seq)
    return done


async def dispatch_plan(
    plan: Plan,
    ledger: Ledger,
    executor: Executor,
    *,
    max_parallel: int = 6,
    parent_seq: int | None = None,
    over_budget: Callable[[], bool] | None = None,
    resume: bool = False,
    checkpoint_each_wave: bool = False,
    max_upstream_chars: int = DEFAULT_MAX_UPSTREAM_CHARS,
    context_provider: ContextProvider | None = None,
    context_budget: ContextBudget | None = None,
    context_meter: ContextBudgetMeter | None = None,
) -> dict[str, Result]:
    """Run a plan's waves through the executor, witnessing every step.

    Appends a ``plan`` entry, then a ``task`` + ``result`` entry per task with
    causal links. Each wave runs concurrently (bounded by ``max_parallel``);
    waves run in dependency order.

    With a ``context_provider``, each task pulls fresh, task-specific context from
    the brain (the ContextProvider seam) before it runs: the context is capped (like
    upstream data), witnessed as its own entry, and the task is chained to it, so a
    parallel or looped agent gets up-to-date context routed to it and the record
    shows exactly what shaped each task. Forum pulls and witnesses the context; it
    never generates it. The pull is synchronous and runs once per task inside the
    wave, so a provider that blocks (does I/O) serializes the wave; keep context()
    fast and offline, as the Protocol advises.

    With ``resume=True`` a task that already has a witnessed successful result in
    the ledger is reused, not re-run, and a ``resume`` entry records which were
    reused; the ledger is the resume state, so no work and no model call is spent
    twice (a reused result reflects the current plan's agent, while its witnessed_seq
    points at the original entry that produced it). With
    ``checkpoint_each_wave=True`` a ``checkpoint`` entry (the Merkle
    root so far) is witnessed and the ledger synced after each wave, a re-checkable
    savepoint and the durability point for batched storage.
    """
    results: dict[str, Result] = {}
    if context_budget is not None and context_meter is None:
        context_meter = ContextBudgetMeter()
    sem = asyncio.Semaphore(max_parallel)
    by_id = {t.id: t for t in plan.tasks}
    waves = plan.schedule()
    completed = _completed_results(ledger, set(by_id)) if resume else {}

    edges = [
        {"from": dep, "to": t.id, "type": "order" if dep in t.order_deps else "data"}
        for t in plan.tasks
        for dep in t.depends_on
    ]
    plan_entry = ledger.append(
        actor="dispatch", kind="plan", payload={"waves": waves, "edges": edges}, causal_parent=parent_seq
    )
    if completed:
        ledger.append(
            actor="dispatch", kind="resume",
            payload={"reused": sorted(completed)}, causal_parent=plan_entry.seq,
        )

    async def run_task(task: Task) -> None:
        async with sem:
            if task.id in completed:
                # reuse the verified result already in the ledger; do not re-run or re-witness
                output, seq = completed[task.id]
                results[task.id] = Result(task.id, task.agent, output, ok=True, witnessed_seq=seq)
                return
            # a data edge feeds its upstream's output into this task; an order edge does not
            if context_budget is not None and context_meter is not None:
                instruction, data_from, upstream_pressures = augment_with_upstream_budgeted(
                    task, results, context_budget=context_budget, context_meter=context_meter
                )
                for pressure in upstream_pressures:
                    ledger.append(
                        actor="context-budget",
                        kind="context_budget",
                        payload=pressure_payload(pressure, context_budget, context_meter),
                        causal_parent=plan_entry.seq,
                    )
            else:
                instruction, data_from = augment_with_upstream(task, results, max_chars=max_upstream_chars)
            # fresh, task-specific context pulled from the brain, capped and witnessed; the
            # task is chained to it so the record shows what shaped it (Forum routes the
            # context to the agent, it never generates it)
            task_parent = plan_entry.seq
            if context_provider is not None:
                # INVARIANT: no await between here and the task append below. context() is
                # sync by contract (the ContextProvider Protocol), so the context pull and
                # the two appends stay one atomic, no-yield window; an await here would let
                # concurrent run_tasks interleave and corrupt seq/prev_hash.
                ctx = context_provider.context(task.instruction)
                if context_budget is not None and context_meter is not None:
                    ctx, pressure = apply_context_budget("task", task.id, ctx, context_budget, context_meter)
                    if pressure.original_tokens > 0:
                        ledger.append(
                            actor="context-budget",
                            kind="context_budget",
                            payload=pressure_payload(pressure, context_budget, context_meter),
                            causal_parent=plan_entry.seq,
                        )
                elif ctx and len(ctx) > max_upstream_chars:
                    # A barer marker than upstream's on purpose: the full context is NOT
                    # witnessed (only this capped slice is), so do not claim it is.
                    ctx = ctx[:max_upstream_chars] + "\n... [truncated for prompt efficiency]"
                if ctx:
                    task_parent = ledger.append(
                        actor="context", kind="context",
                        payload={"task": task.id, "context": ctx}, causal_parent=plan_entry.seq,
                    ).seq
                    instruction = instruction + "\n\nContext for this task:\n" + ctx
            task_payload = {
                "id": task.id,
                "agent": task.agent,
                "instruction": task.instruction,
                "data_from": data_from,
            }
            if task.done_when:
                task_payload["done_when"] = list(task.done_when)
            assigned = ledger.append(
                actor="dispatch",
                kind="task",
                payload=task_payload,
                causal_parent=task_parent,
            )
            if over_budget is not None and over_budget():
                # budget is gone; witness the task without spending a model call
                result = Result(task.id, task.agent, "error: budget exceeded", ok=False)
            else:
                try:
                    result = await executor.run(Assignment(task.id, task.agent, instruction))
                except Exception as exc:
                    result = Result(task.id, task.agent, f"error: {exc}", ok=False)
            entry = ledger.append(
                actor=task.agent,
                kind="result",
                payload={"id": task.id, "output": result.output, "ok": result.ok, "model": executor_id(executor)},
                causal_parent=assigned.seq,
            )
            results[task.id] = dataclasses.replace(result, witnessed_seq=entry.seq)

    for i, wave in enumerate(waves):
        async with asyncio.TaskGroup() as tg:
            for tid in wave:
                tg.create_task(run_task(by_id[tid]))
        if checkpoint_each_wave:
            # a re-checkable savepoint after each wave, and the durability point for batched storage
            ledger.append(
                actor="dispatch", kind="checkpoint",
                payload={"wave": i, "root": ledger.checkpoint()}, causal_parent=plan_entry.seq,
            )
            ledger.sync()

    return results
