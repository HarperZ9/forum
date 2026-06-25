from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable

from forum.executor import Assignment, Executor, Result, executor_id
from forum.ledger import Ledger
from forum.plan import Plan, Task


def augment_with_upstream(task: Task, results: dict[str, Result]) -> tuple[str, list[str]]:
    """Feed a task's data-dependency outputs into its instruction.

    Returns ``(instruction_for_the_executor, the upstream ids actually injected)``. A
    data edge feeds the upstream's witnessed output into the downstream task so it can
    build on real work; an order edge only sequences and injects nothing. A failed
    upstream (ok=False) is not injected: the engine never treats a failure as usable
    work, so a downstream is not handed an error as build-on material, and the returned
    data_from lists only upstreams actually consumed. A data edge whose upstream failed
    thus appears in the plan's edges but not in the downstream's data_from; that
    divergence is a witnessed signal, not a bug.

    Safe to call on concurrent tasks within a wave: it has no await (so it runs
    atomically between scheduling points) and reads only the results of strictly
    earlier waves, which the wave barrier in dispatch_plan guarantees are complete.
    Deterministic: upstreams are injected in depends_on order, deduplicated. The
    upstream output is injected verbatim and uncapped, so a very large or deeply
    chained upstream can grow the prompt; the ledger records the original instruction
    plus data_from, from which the sent prompt is reconstructable at this version.
    """
    parts: list[str] = []
    data_from: list[str] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is not None and up.ok and dep not in data_from:
            parts.append(f"- {dep}: {up.output}")
            data_from.append(dep)
    if not parts:
        return task.instruction, []
    return task.instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from


async def dispatch_plan(
    plan: Plan,
    ledger: Ledger,
    executor: Executor,
    *,
    max_parallel: int = 6,
    parent_seq: int | None = None,
    over_budget: Callable[[], bool] | None = None,
) -> dict[str, Result]:
    """Run a plan's waves through the executor, witnessing every step.

    Appends a ``plan`` entry, then a ``task`` + ``result`` entry per task with
    causal links. Each wave runs concurrently (bounded by ``max_parallel``);
    waves run in dependency order.
    """
    results: dict[str, Result] = {}
    sem = asyncio.Semaphore(max_parallel)
    by_id = {t.id: t for t in plan.tasks}
    waves = plan.schedule()

    edges = [
        {"from": dep, "to": t.id, "type": "order" if dep in t.order_deps else "data"}
        for t in plan.tasks
        for dep in t.depends_on
    ]
    plan_entry = ledger.append(
        actor="dispatch", kind="plan", payload={"waves": waves, "edges": edges}, causal_parent=parent_seq
    )

    async def run_task(task: Task) -> None:
        async with sem:
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

    for wave in waves:
        async with asyncio.TaskGroup() as tg:
            for tid in wave:
                tg.create_task(run_task(by_id[tid]))

    return results
