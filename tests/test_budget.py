import asyncio

from forum.budget import RunBudget
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api"]
model_tier="capable"
executor="echo"
"""
)


class _Exec:
    def __init__(self):
        self.calls = 0

    async def run(self, assignment):
        self.calls += 1
        a = assignment.agent
        if a == "coordinator":
            out = (
                '{"tasks": ['
                '{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []},'
                '{"id": "T2", "agent": "backend", "instruction": "test", "depends_on": []}'
                "]}"
            )
        elif a == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif a == "synthesizer":
            out = "final answer"
        else:
            out = "did it"
        return Result(assignment.task_id, assignment.agent, out)


def _orch(executor):
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    return led, Orchestrator(
        ROSTER, led, executor, Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2)
    )


def test_budget_stops_the_run_and_is_witnessed():
    ex = _Exec()
    led, orch = _orch(ex)
    answer = asyncio.run(orch.submit("build the api", budget=RunBudget(max_model_calls=1)))
    assert answer == "Run stopped: budget exceeded before completion."
    assert len(led.query(kind="budget")) == 1
    assert ex.calls == 1                       # only planning ran; dispatch/validate/synth skipped
    assert led.verify(deep=True) is True       # a budget-stopped run is still fully verifiable


def test_generous_budget_runs_to_completion():
    ex = _Exec()
    led, orch = _orch(ex)
    answer = asyncio.run(orch.submit("build the api", budget=RunBudget(max_model_calls=100)))
    assert answer == "final answer"
    assert led.query(kind="budget") == []
    assert led.verify(deep=True) is True


def test_no_budget_runs_to_completion():
    ex = _Exec()
    led, orch = _orch(ex)
    answer = asyncio.run(orch.submit("build the api"))
    assert answer == "final answer"
    assert led.query(kind="budget") == []


class _Exec1:
    """A one-task plan, so model-call counting is deterministic (no wave concurrency)."""

    def __init__(self):
        self.calls = 0

    async def run(self, assignment):
        self.calls += 1
        a = assignment.agent
        if a == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}'
        elif a == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif a == "synthesizer":
            out = "final answer"
        else:
            out = "did it"
        return Result(assignment.task_id, assignment.agent, out)


def test_validation_calls_count_against_the_budget():
    # plan(1) + task(2) + validate(3) hits a 3-call cap, so synthesis is skipped and
    # the run stops witnessed. This only holds if the validator call is counted, i.e.
    # it routes through the run's counting executor (the bug this guards against).
    ex = _Exec1()
    led, orch = _orch(ex)
    answer = asyncio.run(orch.submit("build the api", budget=RunBudget(max_model_calls=3)))
    assert answer == "Run stopped: budget exceeded before completion."
    assert ex.calls == 3
    assert len(led.query(kind="budget")) == 1
    assert led.verify(deep=True) is True
