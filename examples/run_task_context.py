"""Forum: per-task context, fresh context routed to each agent (v1.12).

A run plans on context from a brain (the ContextProvider seam). This routes that seam
down to every task: each agent pulls fresh, task-specific context at dispatch, capped
and witnessed, so a parallel or looped agent gets up-to-date context tailored to its own
work. Forum pulls, caps, and witnesses the context; the brain supplies it; Forum never
generates it. The executor echoes its prompt so the injected context is visible.

Run:  python examples/run_task_context.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.dispatch import dispatch_plan
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


class Brain:
    """A stand-in ContextProvider: returns context tailored to each task's instruction."""

    def context(self, text: str) -> str:
        facts = {
            "design the auth schema": "Auth uses Postgres; sessions live in Redis.",
            "build the login endpoint": "The login route must rate-limit and log to the ledger.",
        }
        return facts.get(text, "")


class ShowExecutor:
    async def run(self, a):
        return Result(a.task_id, a.agent, a.instruction)  # echo the prompt it received


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    plan = Plan(
        (
            Task("T1", "backend", "design the auth schema", ()),
            Task("T2", "backend", "build the login endpoint", ()),
        )
    )
    results = asyncio.run(dispatch_plan(plan, led, ShowExecutor(), context_provider=Brain()))

    for tid in ("T1", "T2"):
        print(f"{tid} agent saw:")
        print("   ", results[tid].output.replace("\n", "\n    "))
        print()

    print("witnessed per-task context entries:")
    for e in led.query(kind="context"):
        body = led.get_payload(e.payload_hash)
        print(f"  task {body['task']}: {body['context']}")
    print("verify(deep):", led.verify(deep=True))


if __name__ == "__main__":
    main()
