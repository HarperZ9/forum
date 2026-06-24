import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_dispatch_runs_plan_and_witnesses_it():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),
            Task("T3", "docs", "api docs", ("T2",)),
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2))

    assert set(results) == {"T1", "T2", "T3"}
    assert results["T1"].output == "done: schema"
    assert len(ledger.query(kind="result")) == 3
    assert len(ledger.query(kind="task")) == 3
    assert ledger.verify(deep=True) is True


class _TrackingExecutor:
    """Instrumented executor: records the peak number of concurrently-running tasks."""

    def __init__(self):
        self.current = 0
        self.peak = 0

    async def run(self, assignment):
        from forum.executor import Result

        self.current += 1
        self.peak = max(self.peak, self.current)
        await asyncio.sleep(0)  # yield so a sibling task in the same wave can interleave
        self.current -= 1
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


def test_independent_tasks_run_concurrently_and_are_witnessed():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("A", "backend", "a", ()),
            Task("B", "frontend", "b", ()),
            Task("C", "docs", "c", ("A", "B")),
        )
    )
    ex = _TrackingExecutor()
    results = asyncio.run(dispatch_plan(plan, ledger, ex, max_parallel=2))

    assert set(results) == {"A", "B", "C"}
    assert ex.peak >= 2  # A and B were in flight at the same time
    assert ledger.verify(deep=True) is True
    assert plan.schedule()[0] == ["A", "B"]  # they share the first wave
