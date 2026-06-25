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


class _RaisingExecutor:
    """Raises for task 'B' only; succeeds otherwise."""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "B":
            raise RuntimeError("boom")
        return Result(assignment.task_id, assignment.agent, "ok")


def test_failing_task_is_witnessed_and_siblings_survive():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("A", "x", "a", ()),
            Task("B", "x", "b", ()),
            Task("C", "x", "c", ("A", "B")),
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _RaisingExecutor(), max_parallel=2))

    assert results["A"].ok is True
    assert results["B"].ok is False
    assert "boom" in results["B"].output
    assert results["C"].ok is True
    assert len(ledger.query(kind="result")) == 3  # every task got a witnessed result
    assert ledger.verify(deep=True) is True


class _EchoSawExecutor:
    """Echoes the exact instruction it received, so injected upstream output is visible."""

    async def run(self, assignment):
        from forum.executor import Result

        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def _task_entry(ledger, tid):
    return next(
        e for e in ledger.query(kind="task") if ledger.get_payload(e.payload_hash)["id"] == tid
    )


def test_data_edge_feeds_upstream_output_downstream():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),  # data edge (the default)
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), max_parallel=2))

    assert "Upstream results you build on:" in results["T2"].output
    assert "T1: schema" in results["T2"].output            # T2 saw T1's output
    body = ledger.get_payload(_task_entry(ledger, "T2").payload_hash)
    assert body["data_from"] == ["T1"]                     # witnessed: T2 consumed T1
    assert body["instruction"] == "endpoint"              # the witnessed instruction stays original
    assert ledger.verify(deep=True) is True


def test_order_edge_does_not_feed_output():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "ops", "notify", ("T1",), frozenset({"T1"})),  # order edge
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), max_parallel=2))

    assert results["T2"].output == "notify"                # nothing injected
    assert ledger.get_payload(_task_entry(ledger, "T2").payload_hash)["data_from"] == []


class _FailFirstExecutor:
    """T1 fails (ok=False); everyone else echoes the instruction they received."""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "T1":
            return Result("T1", assignment.agent, "boom", ok=False)
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def test_failed_upstream_is_not_fed_downstream():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),  # data edge on a FAILING upstream
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _FailFirstExecutor(), max_parallel=2))

    assert results["T1"].ok is False
    assert results["T2"].output == "endpoint"   # no error injected; T2 ran on its own instruction
    assert "boom" not in results["T2"].output
    body = ledger.get_payload(_task_entry(ledger, "T2").payload_hash)
    assert body["data_from"] == []              # a failed upstream is not "consumed"
    # the edge is still declared in the plan, so edges-minus-data_from is a witnessed signal
    edges = ledger.get_payload(ledger.query(kind="plan")[0].payload_hash)["edges"]
    assert {"from": "T1", "to": "T2", "type": "data"} in edges
    assert ledger.verify(deep=True) is True


def test_plan_entry_witnesses_typed_edges():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "x", "a", ()),
            Task("T2", "x", "b", ("T1",)),                     # data
            Task("T3", "x", "c", ("T1",), frozenset({"T1"})),  # order
        )
    )
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2))
    edges = ledger.get_payload(ledger.query(kind="plan")[0].payload_hash)["edges"]
    assert {"from": "T1", "to": "T2", "type": "data"} in edges
    assert {"from": "T1", "to": "T3", "type": "order"} in edges
