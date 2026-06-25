import asyncio

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
keywords=["api","database","schema","auth"]
model_tier="capable"
executor="echo"
"""
)


class _Scripted:
    def __init__(self):
        self.seen_ids = []

    async def run(self, assignment):
        self.seen_ids.append((assignment.agent, assignment.task_id))
        agent = assignment.agent
        if agent == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}'
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "good"}'
        elif agent == "synthesizer":
            out = "done"
        else:
            out = "built"
        return Result(assignment.task_id, assignment.agent, out)


def _orch(ledger, executor=None):
    return Orchestrator(
        ROSTER, ledger, executor or _Scripted(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
    )


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_verdict_causal_chain_reaches_its_result_and_the_request():
    ledger = _ledger()
    asyncio.run(_orch(ledger).submit("build the api"))
    verdicts = ledger.query(kind="verdict")
    assert len(verdicts) == 1
    # the verdict's parent is the specific result entry it judged
    parent = ledger.get(verdicts[0].causal_parent)
    assert parent.kind == "result"
    # and the full chain reconstructs request -> plan -> task -> result -> verdict
    kinds = [e.kind for e in ledger.causal_chain(verdicts[0].seq)]
    assert kinds[0] == "request"
    assert kinds[-1] == "verdict"
    assert "result" in kinds and "task" in kinds and "plan" in kinds


def test_failed_task_verdict_also_parents_its_result():
    class _Failing:
        async def run(self, assignment):
            agent = assignment.agent
            if agent == "coordinator":
                return Result(assignment.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "x", "depends_on": []}]}')
            if agent == "synthesizer":
                return Result(assignment.task_id, agent, "answer")
            if agent == "backend":
                return Result(assignment.task_id, agent, "error: boom", ok=False)
            return Result(assignment.task_id, agent, '{"ok": true, "score": 1.0, "reason": "x"}')

    ledger = _ledger()
    asyncio.run(_orch(ledger, _Failing()).submit("build"))
    verdicts = ledger.query(kind="verdict")
    assert len(verdicts) == 1
    parent = ledger.get(verdicts[0].causal_parent)
    assert parent.kind == "result"  # even a failed task's verdict points at its result entry


def test_control_roles_get_distinct_assignment_ids():
    ledger = _ledger()
    scripted = _Scripted()
    asyncio.run(_orch(ledger, scripted).submit("build the api"))
    control_ids = {agent: tid for agent, tid in scripted.seen_ids if tid.startswith("control")}
    # each control role is called with a role-specific id, not a shared "control" sentinel
    assert control_ids.get("coordinator") == "control:coordinator"
    assert control_ids.get("validator") == "control:validator"
    assert control_ids.get("synthesizer") == "control:synthesizer"


def test_empty_plan_submit_still_answers_and_verifies():
    class _EmptyPlan:
        async def run(self, assignment):
            if assignment.agent == "coordinator":
                return Result(assignment.task_id, assignment.agent, '{"tasks": []}')
            if assignment.agent == "synthesizer":
                return Result(assignment.task_id, assignment.agent, "nothing to do")
            return Result(assignment.task_id, assignment.agent, "x")

    ledger = _ledger()
    answer = asyncio.run(_orch(ledger, _EmptyPlan()).submit("do nothing"))
    assert answer == "nothing to do"
    assert ledger.query(kind="verdict") == []  # no tasks, no verdicts
    assert ledger.verify(deep=True) is True
