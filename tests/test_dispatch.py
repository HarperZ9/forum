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
