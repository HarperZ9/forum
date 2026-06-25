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


class _Exec:
    def __init__(self):
        self.calls = []

    async def run(self, assignment):
        self.calls.append(assignment.agent)
        if assignment.agent == "classifier":
            return Result(assignment.task_id, assignment.agent, '{"agent": "backend", "confidence": 0.8, "reason": "best fit"}')
        if assignment.agent == "validator":
            return Result(assignment.task_id, assignment.agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        return Result(assignment.task_id, assignment.agent, "did it")


def _orch(ledger, ex):
    return Orchestrator(ROSTER, ledger, ex, Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2))


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_assign_uses_router_when_keywords_decide():
    ledger = _ledger()
    ex = _Exec()
    agent = asyncio.run(_orch(ledger, ex).assign("build the api database schema"))
    assert agent == "backend"
    assert "classifier" not in ex.calls            # the router decided, no escalation
    assert ledger.query(kind="route")
    assert ledger.query(kind="classification") == []


def test_assign_escalates_to_classifier_when_keywords_cannot_decide():
    ledger = _ledger()
    ex = _Exec()
    agent = asyncio.run(_orch(ledger, ex).assign("write a haiku about the sea"))
    assert agent == "backend"                       # the classifier chose it
    assert "classifier" in ex.calls                 # the ladder escalated to Tier-2
    routes = ledger.query(kind="route")
    assert routes and ledger._s.get_payload(routes[0].payload_hash)["decided"] is None
    classifications = ledger.query(kind="classification")
    assert classifications  # the classification is witnessed
    # the classification chains back to the route that escalated to it
    assert ledger.get(classifications[0].causal_parent).kind == "route"


def test_submit_one_runs_validates_and_verifies():
    ledger = _ledger()
    ex = _Exec()
    result = asyncio.run(_orch(ledger, ex).submit_one("build the api"))
    assert result.ok is True and result.output == "did it"
    assert ledger.query(kind="request") and ledger.query(kind="verdict")
    assert ledger.verify(deep=True) is True
    # the verdict chains back through the result to the request
    verdict = ledger.query(kind="verdict")[0]
    assert ledger.get(verdict.causal_parent).kind == "result"
