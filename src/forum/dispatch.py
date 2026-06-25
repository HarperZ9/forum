from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable

from forum.executor import Assignment, Executor, Result
from forum.ledger import Ledger
from forum.plan import Plan, Task


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

    plan_entry = ledger.append(
        actor="dispatch", kind="plan", payload={"waves": waves}, causal_parent=parent_seq
    )

    async def run_task(task: Task) -> None:
        async with sem:
            assigned = ledger.append(
                actor="dispatch",
                kind="task",
                payload={"id": task.id, "agent": task.agent, "instruction": task.instruction},
                causal_parent=plan_entry.seq,
            )
            if over_budget is not None and over_budget():
                # budget is gone; witness the task without spending a model call
                result = Result(task.id, task.agent, "error: budget exceeded", ok=False)
            else:
                try:
                    result = await executor.run(Assignment(task.id, task.agent, task.instruction))
                except Exception as exc:
                    result = Result(task.id, task.agent, f"error: {exc}", ok=False)
            entry = ledger.append(
                actor=task.agent,
                kind="result",
                payload={"id": task.id, "output": result.output, "ok": result.ok},
                causal_parent=assigned.seq,
            )
            results[task.id] = dataclasses.replace(result, witnessed_seq=entry.seq)

    for wave in waves:
        async with asyncio.TaskGroup() as tg:
            for tid in wave:
                tg.create_task(run_task(by_id[tid]))

    return results
