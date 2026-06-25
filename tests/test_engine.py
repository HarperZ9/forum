import asyncio

from forum.control import Coordinator, Synthesizer, Validator
from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api","database","schema","auth"]
model_tier="capable"
executor="echo"
"""
)


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_route_decides_a_lane():
    orch = _orchestrator(make_ledger())
    assert orch.route("build the database schema").decided == "backend"


def test_submit_plan_runs_and_is_verifiable():
    ledger = make_ledger()
    orch = _orchestrator(ledger)
    plan = Plan((Task("T1", "backend", "schema", ()), Task("T2", "backend", "auth", ("T1",))))
    results = asyncio.run(orch.submit_plan(plan))
    assert set(results) == {"T1", "T2"}
    assert ledger.query(kind="request")  # a request was witnessed
    assert ledger.verify(deep=True) is True


def _orchestrator(ledger):
    return Orchestrator(
        ROSTER, ledger, EchoExecutor(), Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2)
    )


class _ScriptedExecutor:
    """Returns a different canned reply depending on which control role calls it."""

    async def run(self, assignment):
        from forum.executor import Result

        agent = assignment.agent
        if agent == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}'
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "good"}'
        elif agent == "synthesizer":
            out = "final answer: built"
        else:
            out = "did: " + assignment.instruction
        return Result(assignment.task_id, assignment.agent, out)


def test_submit_plans_executes_and_answers():
    ledger = make_ledger()
    orch = Orchestrator(
        ROSTER, ledger, _ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
    )
    answer = asyncio.run(orch.submit("build the backend"))

    assert answer == "final answer: built"
    assert ledger.query(kind="request")
    assert ledger.query(kind="verdict")  # the result was validated
    assert ledger.verify(deep=True) is True
