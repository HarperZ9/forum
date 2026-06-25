from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable

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
    if not parts:
        return task.instruction, []
    return task.instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from


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
) -> dict[str, Result]:
    """Run a plan's waves through the executor, witnessing every step.

    Appends a ``plan`` entry, then a ``task`` + ``result`` entry per task with
    causal links. Each wave runs concurrently (bounded by ``max_parallel``);
    waves run in dependency order.

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
            instruction, data_from = augment_with_upstream(task, results)
            assigned = ledger.append(
                actor="dispatch",
                kind="task",
                payload={"id": task.id, "agent": task.agent, "instruction": task.instruction, "data_from": data_from},
                causal_parent=plan_entry.seq,
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
